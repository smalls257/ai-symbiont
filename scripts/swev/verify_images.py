"""Check every picked task's official image on Docker Hub by metadata query (no pull).

A missing image would surface hours into a run; a task that fails the check is named and the
script exits 1. Rewrites the task list in place with image_verified and image_gb.
Usage: python verify_images.py <swev-django-tasks.json>
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HUB = "https://hub.docker.com/v2/namespaces/{namespace}/repositories/{repo}/tags/{tag}"
TIMEOUT_S = 30


def tag_url(image: str) -> str:
    """Docker Hub tag-metadata URL for `namespace/repo:tag` (tag defaults to latest)."""
    name, _, tag = image.partition(":")
    namespace, _, repo = name.partition("/")
    if not repo:
        raise ValueError(f"image {image!r} has no namespace")
    return HUB.format(namespace=namespace, repo=repo, tag=tag or "latest")


def image_status(image: str) -> dict:
    """{"image_verified": bool, "image_gb": float | None} from the tag's metadata."""
    try:
        with urllib.request.urlopen(tag_url(image), timeout=TIMEOUT_S) as resp:  # noqa: S310  fixed https host
            meta = json.load(resp)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {"image_verified": False, "image_gb": None}
        raise
    active = meta.get("tag_status") == "active"
    size = meta.get("full_size")
    return {"image_verified": active, "image_gb": round(size / 1e9, 2) if size else None}


def main(path: Path) -> int:
    listed = json.loads(path.read_text())
    for task in listed["tasks"]:
        task |= image_status(task["docker_image"])
    missing = [t["instance_id"] for t in listed["tasks"] if not t["image_verified"]]
    listed["images_verified"] = len(listed["tasks"]) - len(missing)
    listed["images_gb_total"] = round(sum(t["image_gb"] or 0 for t in listed["tasks"]), 1)
    path.write_text(json.dumps(listed, indent=1))
    print(
        json.dumps(
            {
                "verified": listed["images_verified"],
                "missing": missing,
                "gb_total": listed["images_gb_total"],
            }
        )
    )
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
