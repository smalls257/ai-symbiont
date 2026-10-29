"""The PLUG-AGENT-1 judge as a loopback service: one Llama 3.2 1B, three LoRA seeds, mean P(yes).

POST /score {"pairs": [{"system", "prompt"}]} answers {"p_yes": [...]}: for each pair, P(yes)
against P(no) at the next token (score_pairs_torch's rule), averaged over the adapters. Bound to
127.0.0.1 only; logs counts and seconds, never pair text. LCAP_DEVICE picks cuda, mps or cpu.
Usage: python plug_judge_server.py --model M --adapter A0 --adapter A1 --adapter A2 [--port P]
"""

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from statistics import mean

import torch
from peft import PeftModel
from score_pairs_torch import BATCH, prompt_of, single_token, yes_probability
from train_lora_torch import DEVICE
from transformers import AutoModelForCausalLM, AutoTokenizer

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8765


class Judge:
    """Base model and named adapters, loaded once."""

    def __init__(self, model_path: str, adapters: list[str]):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.yes = single_token(self.tokenizer, "yes")
        self.no = single_token(self.tokenizer, "no")
        base = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.bfloat16).to(DEVICE)
        self.names = [f"s{index}" for index in range(len(adapters))]
        self.model = PeftModel.from_pretrained(base, adapters[0], adapter_name=self.names[0])
        for name, path in zip(self.names[1:], adapters[1:], strict=True):
            self.model.load_adapter(path, adapter_name=name)
        self.model.eval()

    def score(self, pairs: list[dict[str, str]]) -> list[float]:
        """Mean P(yes) over the adapters, per pair."""
        prompts = [
            prompt_of(self.tokenizer, {"context": pair["system"], "text": pair["prompt"]})
            for pair in pairs
        ]
        per_adapter = []
        for name in self.names:
            self.model.set_adapter(name)
            found: list[float] = []
            for start in range(0, len(prompts), BATCH):
                chunk = prompts[start : start + BATCH]
                found += yes_probability(self.model, self.tokenizer, chunk, self.yes, self.no)
            per_adapter.append(found)
        return [mean(column) for column in zip(*per_adapter, strict=True)]


def score_requests_for(judge: Judge) -> type[BaseHTTPRequestHandler]:
    """The POST /score endpoint bound to `judge`."""

    class ScoreRequests(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 http.server's name
            if self.path != "/score":
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            started = time.monotonic()
            found = judge.score(body["pairs"])
            seconds = time.monotonic() - started
            print(f"scored={len(found)} seconds={seconds:.1f}", file=sys.stderr, flush=True)
            reply = json.dumps({"p_yes": found}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args) -> None:
            """Request lines carry no text, but the score line above already counts them."""

    return ScoreRequests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", action="append", required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    judge = Judge(args.model, args.adapter)
    print(f"judge ready on {LOOPBACK}:{args.port} adapters={len(args.adapter)}", file=sys.stderr)
    HTTPServer(
        (LOOPBACK, args.port), score_requests_for(judge)
    ).serve_forever()  # one model: serial


if __name__ == "__main__":
    main()
