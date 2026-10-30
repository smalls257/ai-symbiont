"""PLUG-AGENT-2 infrastructure smoke: one plain Glimmer run of one task, with the server's speeds.

Containers run on the desktop, the model on the owner's laptop (SYMBIONT_GLIMMER_URL; the bearer
key is read from OPENAI_API_KEY by litellm and never enters a config or trajectory). Prints one
JSON line: outcome, steps, wall time and the server's own prompt and generation speeds.
Usage: python plug_agent2_smoke_one.py <rows.json> <instance_id> <out-dir>
"""

import json
import subprocess
import sys
from pathlib import Path

from plug_agent_env import run_task
from plug_agent_notes import NoteArm, NoteSource

SETTINGS = {
    "agent": "glimmer",
    "run_label": "plug-agent-2-smoke",
    "step_limit": 75,
    "wall_limit_min": 45,
    "temperature": 0,
}


def server_speeds(traj: Path) -> dict:
    """Tokens per second the server reported over the run's calls (prompt, generation)."""
    timings = [
        (message.get("extra") or {}).get("response", {}).get("timings") or {}
        for message in json.loads(traj.read_text())["messages"]
        if message["role"] == "assistant"
    ]
    prompt_ms = sum(t.get("prompt_ms", 0) for t in timings)
    predicted_ms = sum(t.get("predicted_ms", 0) for t in timings)
    prompt_n = sum(t.get("prompt_n", 0) for t in timings)
    predicted_n = sum(t.get("predicted_n", 0) for t in timings)
    return {
        "calls": len(timings),
        "prompt_tokens_processed": prompt_n,
        "prompt_tok_s": round(1000 * prompt_n / prompt_ms, 1) if prompt_ms else None,
        "generated_tokens": predicted_n,
        "generation_tok_s": round(1000 * predicted_n / predicted_ms, 1) if predicted_ms else None,
    }


def main() -> None:
    rows = {row["instance_id"]: row for row in json.loads(Path(sys.argv[1]).read_text())}
    row = rows[sys.argv[2]]
    out = Path(sys.argv[3])
    traj = out / "traj" / f"{row['instance_id']}.traj.json"
    traj.parent.mkdir(parents=True, exist_ok=True)
    source = NoteSource(NoteArm.NONE, row["repo"], (), 0.0, 1.0)
    record = run_task(row, source, SETTINGS, traj)
    subprocess.run(["docker", "rmi", row["docker_image"]], capture_output=True, check=False)
    speeds = server_speeds(traj) if traj.is_file() else {}
    keep = ("instance_id", "resolved", "error_kind", "exit_status", "agent_steps", "wall_s")
    print(json.dumps({k: record.get(k) for k in keep} | speeds))


if __name__ == "__main__":
    main()
