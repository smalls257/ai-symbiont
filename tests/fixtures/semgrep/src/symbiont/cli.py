"""Fixture: cli.py may print, but never a prompt. Every `# expect:` line must be reported."""

import sys


def show(prompt, reply, count):
    print(prompt)  # expect: sym-no-prompt-logging
    print(f"sent {prompt}")  # expect: sym-no-prompt-logging
    print("got", reply.text)  # expect: sym-no-prompt-logging
    sys.stderr.write(prompt)  # expect: sym-no-prompt-logging
    print(f"sent {count} bytes")
    print("sent", len(prompt))
