"""The judge as a loopback service: one Llama 3.2 1B, LoRA adapters, mean P(yes).

POST /score {"pairs": [{"system", "prompt"}]} -> {"p_yes": [...]}, averaged over the adapters.
POST /reload {"adapter": DIR} serves only the adapter in DIR -> {"loaded": DIR}; a bad DIR answers
400 and the old adapters stay. Bound to 127.0.0.1; logs counts and seconds, never pair text.
Usage: python plug_judge_server.py --model M --adapter A0 [--adapter A1 ...] [--port P]
"""

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from statistics import mean

import torch
from peft import PeftModel
from score_pairs_torch import BATCH, prompt_of, single_token, yes_probability
from train_lora_torch import DEVICE
from transformers import AutoModelForCausalLM, AutoTokenizer

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8791  # 8765 is taken on the laptop


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
        self.generation = 0

    def reload(self, path: str) -> None:
        """Serve only the adapter in `path` from now on; raises (and keeps serving the old
        adapters) when it cannot be loaded."""
        if not Path(path, "adapter_config.json").is_file():
            raise FileNotFoundError(f"{path} holds no adapter_config.json")
        self.generation += 1
        fresh = f"n{self.generation}"
        self.model.load_adapter(path, adapter_name=fresh)
        self.model.set_adapter(fresh)
        for old in self.names:
            self.model.delete_adapter(old)
        self.names = [fresh]

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


def send_json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    """One JSON reply."""
    reply = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(reply)))
    handler.end_headers()
    handler.wfile.write(reply)


def requests_for(judge: Judge) -> type[BaseHTTPRequestHandler]:
    """The POST /score and /reload endpoints bound to `judge`."""

    class Requests(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 http.server's name
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/score":
                self.score(body)
            elif self.path == "/reload":
                self.reload(body)
            else:
                self.send_error(404)

        def score(self, body: dict) -> None:
            started = time.monotonic()
            found = judge.score(body["pairs"])
            seconds = time.monotonic() - started
            print(f"scored={len(found)} seconds={seconds:.1f}", file=sys.stderr, flush=True)
            send_json(self, 200, {"p_yes": found})

        def reload(self, body: dict) -> None:
            started = time.monotonic()
            try:
                judge.reload(body["adapter"])
            except (OSError, ValueError, KeyError) as unusable:
                print(f"reload refused: {type(unusable).__name__}", file=sys.stderr, flush=True)
                send_json(self, 400, {"error": str(unusable)})
                return
            seconds = time.monotonic() - started
            print(f"reloaded adapters=1 seconds={seconds:.1f}", file=sys.stderr, flush=True)
            send_json(self, 200, {"loaded": body["adapter"]})

        def log_message(self, *args) -> None:
            """Request lines carry no text, but the lines above already count them."""

    return Requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", action="append", required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    judge = Judge(args.model, args.adapter)
    print(f"judge ready on {LOOPBACK}:{args.port} adapters={len(args.adapter)}", file=sys.stderr)
    HTTPServer((LOOPBACK, args.port), requests_for(judge)).serve_forever()  # one model: serial


if __name__ == "__main__":
    main()
