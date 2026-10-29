"""Put a repo's personal Glimmer name into the llama-server router preset, keeping plain plain.

The personal section is the plain section's settings plus one `lora` line. A preset with no plain
section, or whose plain section already loads a LoRA, stops the install rather than hide a plain
model that no longer answers plain. Other sections and comments are kept. Stdlib only (host).

Usage: python3 glimmer_preset.py --preset P --plain NAME --personal NAME --lora PATH
"""

import argparse
import os
import sys
from pathlib import Path

LORA_KEYS = ("lora", "lora-scaled", "lora-init-without-apply")


class PresetError(ValueError):
    """The preset cannot take a personal model without breaking the plain one."""


def split_sections(text: str) -> list[tuple[str | None, list[str]]]:
    """(section name, its lines including the header) in file order; None for the preamble."""
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            blocks.append((stripped[1:-1].strip(), []))
        blocks[-1][1].append(line)
    return blocks


def settings(lines: list[str]) -> list[tuple[str, str]]:
    """The `key = value` pairs of one section, comments and blank lines skipped."""
    pairs = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#")) or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        pairs.append((key.strip(), value.strip()))
    return pairs


def with_personal_model(text: str, plain: str, personal: str, lora: str) -> str:
    """The preset with `personal` = `plain`'s settings + `lora`; raises PresetError."""
    if plain == personal:
        raise PresetError("the personal name must differ from the plain name")
    blocks = split_sections(text)
    section = [f"[{personal}]\n", *_plain_body(blocks, plain), f"lora = {lora}\n"]
    kept = [lines for name, lines in blocks if name != personal]
    joined = "".join(line for lines in kept for line in lines)
    return joined.rstrip("\n") + "\n\n" + "".join(section)


def _plain_body(blocks: list[tuple[str | None, list[str]]], plain: str) -> list[str]:
    """The plain section's settings as lines; raises when it is missing or loads a LoRA."""
    found = [lines for name, lines in blocks if name == plain]
    if not found:
        raise PresetError(f"no [{plain}] section: the plain model must exist before a personal one")
    pairs = settings(found[0])
    if any(key in LORA_KEYS for key, _ in pairs):
        raise PresetError(f"[{plain}] already loads a LoRA; plain Glimmer must have no adapter")
    return [f"{key} = {value}\n" for key, value in pairs]


def install(preset: Path, plain: str, personal: str, lora: str) -> None:
    """Rewrite `preset` in place, atomically, so a crash never leaves half a file."""
    updated = with_personal_model(preset.read_text(encoding="utf-8"), plain, personal, lora)
    staged = preset.with_name(preset.name + ".next")
    staged.write_text(updated, encoding="utf-8")
    os.replace(staged, preset)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preset", type=Path, required=True)
    parser.add_argument("--plain", required=True)
    parser.add_argument("--personal", required=True)
    parser.add_argument("--lora", required=True)
    args = parser.parse_args()
    try:
        install(args.preset, args.plain, args.personal, args.lora)
    except (OSError, PresetError) as refused:
        print(f"glimmer_preset: {refused}", file=sys.stderr)
        sys.exit(1)
    print(f"glimmer_preset: [{args.personal}] = [{args.plain}] + lora {Path(args.lora).name}")


if __name__ == "__main__":
    main()
