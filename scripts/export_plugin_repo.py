"""Export the product-only tree that github.com/smalls257/ai-symbiont-plugin publishes.

Users install from that repo (`PLUGIN_SOURCE`), so an install never downloads research code. The
tree is the committed product paths at a ref minus pyproject's `source-exclude`, the same list the
wheel uses. It never runs git in the output. Exit codes: 0 exported, 1 a check failed, 2 bad args.

Usage: uv run python scripts/export_plugin_repo.py --out ../ai-symbiont-plugin [--ref HEAD]
"""

import argparse
import fnmatch
import io
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
# What an install needs: the package, the plugin and its marketplace entry, the installers.
PRODUCT_PATHS = (
    ".claude-plugin",
    ".gitattributes",
    "LICENSE",
    "install.ps1",
    "install.sh",
    "plugin",
    "pyproject.toml",
    "src/symbiont",
    "uv.lock",
)
README_SOURCE = "plugin/symbiont/README.md"
# Words that only research code carries; finding one in the export means a path slipped through.
RESEARCH_MARKERS = (
    "api.meta.ai",
    "META_API_KEY",
    "symbiont.act1",
    "symbiont.eval",
    "symbiont.routeb",
)


class ExportError(RuntimeError):
    """A check on the exported tree failed; the message names the file."""


def research_globs(pyproject: bytes) -> list[str]:
    """The source-exclude globs from pyproject.toml: the one list of research paths."""
    table = tomllib.loads(pyproject.decode())["tool"]["uv"]["build-backend"]
    return list(table["source-exclude"])


def is_research(path: str, globs: list[str]) -> bool:
    """True when `path` is, or sits under, a path matched by one of the globs."""
    pure = PurePosixPath(path)
    candidates = [str(pure), *(str(parent) for parent in pure.parents)]
    return any(fnmatch.fnmatchcase(candidate, glob) for glob in globs for candidate in candidates)


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def committed_files(ref: str) -> dict[str, bytes]:
    """Every product file at `ref`, read from git so only committed content is exported."""
    files = {}
    with tarfile.open(fileobj=io.BytesIO(_git("archive", ref, *PRODUCT_PATHS))) as archive:
        for member in archive.getmembers():
            handle = archive.extractfile(member) if member.isfile() else None
            if handle is not None:
                files[member.name] = handle.read()
    return files


def product_tree(files: dict[str, bytes], commit: str) -> dict[str, bytes]:
    """The product files minus research, plus the README and a note of where they came from."""
    globs = research_globs(files["pyproject.toml"])
    tree = {path: body for path, body in files.items() if not is_research(path, globs)}
    tree["README.md"] = files[README_SOURCE]
    tree["EXPORTED_FROM"] = f"https://github.com/smalls257/ai-symbiont {commit}\n".encode()
    return tree


def check_tree(tree: dict[str, bytes], globs: list[str]) -> None:
    """Raise ExportError on a research path or a research marker anywhere in the tree."""
    for path, body in sorted(tree.items()):
        if is_research(path, globs):
            raise ExportError(f"{path} is research code (pyproject source-exclude)")
        text = body.decode(errors="replace")
        found = [marker for marker in RESEARCH_MARKERS if marker in text]
        if found:
            raise ExportError(f"{path} mentions {', '.join(found)}")


def write_tree(tree: dict[str, bytes], out: Path) -> None:
    """Write every file under `out`, keeping the executable bit on the shell scripts."""
    for path, body in tree.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        if path.endswith(".sh"):
            target.chmod(0o755)


def export_files(files: dict[str, bytes], commit: str, out: Path) -> int:
    """Check the product tree built from `files` and write it; returns the number of files."""
    tree = product_tree(files, commit)
    check_tree(tree, research_globs(files["pyproject.toml"]))
    write_tree(tree, out)
    return len(tree)


def export(ref: str, out: Path) -> int:
    """Export the committed tree at `ref`; returns the number of files written."""
    commit = _git("rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    return export_files(committed_files(commit), commit, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="a directory that does not exist")
    parser.add_argument("--ref", default="HEAD", help="the commit to export (default HEAD)")
    args = parser.parse_args(argv)
    if args.out.exists():
        print(f"{args.out} already exists; export into a new directory", file=sys.stderr)
        return 2
    try:
        count = export(args.ref, args.out)
    except ExportError as failed:
        print(f"export refused: {failed}", file=sys.stderr)
        return 1
    print(f"exported {count} files to {args.out}; review, then commit and push it yourself")
    return 0


if __name__ == "__main__":
    sys.exit(main())
