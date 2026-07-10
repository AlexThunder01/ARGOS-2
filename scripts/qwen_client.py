#!/usr/bin/env python3
"""Quick test client for the vLLM Qwen3 server."""

import argparse
import json
from urllib.request import Request, urlopen

BASE = "http://localhost:8000/v1"


def chat(prompt: str, base: str = BASE, stream: bool = False) -> None:
    payload = json.dumps(
        {
            "model": "qwen3",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0.7,
            "stream": stream,
        }
    ).encode()

    req = Request(
        f"{base}/chat/completions", data=payload, headers={"Content-Type": "application/json"}
    )

    with urlopen(req) as resp:
        if stream:
            for line in resp:
                line = line.decode().strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    print(delta, end="", flush=True)
            print()
        else:
            data = json.loads(resp.read())
            print(data["choices"][0]["message"]["content"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?", default="Ciao! Chi sei?")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args()
    chat(args.prompt, base=args.base, stream=args.stream)


if __name__ == "__main__":
    main()
