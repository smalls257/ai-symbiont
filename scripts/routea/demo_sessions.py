"""Write the Route A demo's synthetic history: hand-written OpenHands trajectories, no real data.

Three past sessions in a made-up project, each with a failure and the change that fixed it, so
mining finds lessons with known resolutions. Synthetic and public by construction; the files go
to the demo's work directory, never into the repo.

    uv run python scripts/routea/demo_sessions.py OUT_DIR
"""

import json
import sys
from pathlib import Path
from typing import Any

PROJECT = "demo-shop"
WORKSPACE = f"/workspace/{PROJECT}"

Step = tuple[str, ...]  # ("bash", command, output, exit) or ("edit", path, old, new)

SESSIONS: dict[str, list[Step]] = {
    "demo-shop-1": [
        (
            "bash",
            "python -m pytest tests/test_cart.py -q",
            "E   ModuleNotFoundError: No module named 'shop'",
            "1",
        ),
        ("bash", "pip install -e .", "Successfully installed demo-shop-0.1", "0"),
        ("bash", "python -m pytest tests/test_cart.py -q", "4 passed in 0.12s", "0"),
    ],
    "demo-shop-2": [
        (
            "bash",
            "python -m pytest tests/test_prices.py -q",
            "shop/prices.py:12: in total\nE   NameError: name 'Decimal' is not defined",
            "1",
        ),
        ("edit", "shop/prices.py", "import math\n", "import math\nfrom decimal import Decimal\n"),
        ("bash", "python -m pytest tests/test_prices.py -q", "6 passed in 0.08s", "0"),
    ],
    "demo-shop-3": [
        (
            "bash",
            "python manage.py migrate",
            "django.db.utils.OperationalError: no such table: shop_order",
            "1",
        ),
        (
            "bash",
            "python manage.py makemigrations shop",
            "Migrations for 'shop': 0002_order.py",
            "0",
        ),
        ("bash", "python manage.py migrate", "Applying shop.0002_order... OK", "0"),
    ],
}


def _call(call_id: str, step: Step) -> tuple[dict[str, Any], str]:
    if step[0] == "bash":
        _, command, output, code = step
        arguments = {"command": command}
        observed = f"{output}\n[The command completed with exit code {code}.]"
        return _function("execute_bash", call_id, arguments), observed
    _, path, old, new = step
    arguments = {"command": "str_replace", "path": f"{WORKSPACE}/{path}"}
    arguments |= {"old_str": old, "new_str": new}
    observed = f"The file {WORKSPACE}/{path} has been edited."
    return _function("str_replace_editor", call_id, arguments), observed


def _function(name: str, call_id: str, arguments: dict[str, str]) -> dict[str, Any]:
    function = {"name": name, "arguments": json.dumps(arguments)}
    return {"id": call_id, "type": "function", "function": function}


def trajectory(session_id: str, steps: list[Step]) -> dict[str, object]:
    """One OpenHands trajectory row in the shape `symbiont.readers.openhands` reads."""
    issue = f"<uploaded_files>\n{WORKSPACE}\n</uploaded_files>\n\nFix the failing tests."
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "Synthetic demo agent."},
        {"role": "user", "content": issue},
    ]
    for index, step in enumerate(steps):
        call, observed = _call(f"{session_id}-{index}", step)
        name = call["function"]["name"]
        messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
        messages.append(
            {"role": "tool", "content": observed, "name": name, "tool_call_id": call["id"]}
        )
    return {
        "trajectory_id": session_id,
        "instance_id": f"{session_id}-task",
        "repo": PROJECT,
        "trajectory": messages,
    }


def main() -> None:
    out = Path(sys.argv[1]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{PROJECT}.jsonl"
    rows = [trajectory(sid, steps) for sid, steps in SESSIONS.items()]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
