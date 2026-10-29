"""The nightly job's configuration: one TOML file outside the repo, never a committed address.

The file names the training host only by an ssh destination (an alias in ~/.ssh/config keeps the
address out of this file too), the repo checkout and env file on that host, and one `[[repo]]`
table per repo that gets its own personal Glimmer. A missing or malformed key raises naming the
key; nothing falls back to a guessed host or path. See `nightly.example.toml`.
"""

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_VARIABLE = "SYMBIONT_NIGHTLY_CONFIG"
DEFAULT_CONFIG = Path.home() / ".config" / "symbiont" / "nightly.toml"
DEFAULT_DATA_DIR = Path.home() / ".symbiont"
DEFAULT_MODEL_PREFIX = "Muse-Glimmer-30B"
# A repo name becomes part of a model name, a host path and a preset section header.
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class ConfigError(ValueError):
    """The nightly config is missing, unreadable or names a key wrongly."""


@dataclass(frozen=True)
class HostConfig:
    """Where training runs: ssh destination, the repo checkout and env file there, a work root."""

    ssh: str
    checkout: str
    env_file: str
    work_root: str
    model_prefix: str = DEFAULT_MODEL_PREFIX

    @property
    def host_script(self) -> str:
        """The host half of the nightly job, in the host's checkout."""
        return f"{self.checkout}/ops/routeb_nightly_host.sh"


@dataclass(frozen=True)
class RepoConfig:
    """One repo with its own personal model: its name, its store project, its logs, its hold-out."""

    name: str
    project: str
    sources: tuple[str, ...] = ()
    held_out: frozenset[str] = frozenset()


@dataclass(frozen=True)
class NightlyConfig:
    """Everything one night needs."""

    host: HostConfig
    repos: tuple[RepoConfig, ...]
    data_dir: Path = DEFAULT_DATA_DIR


def config_path(given: Path | None) -> Path:
    """--config, else $SYMBIONT_NIGHTLY_CONFIG, else ~/.config/symbiont/nightly.toml."""
    if given is not None:
        return given
    return Path(os.environ.get(CONFIG_VARIABLE) or DEFAULT_CONFIG)


def load_config(path: Path) -> NightlyConfig:
    """Parse and check the file; raises ConfigError naming the file and the key."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as unreadable:
        raise ConfigError(f"{path}: {unreadable}") from unreadable
    repos = raw.get("repo")
    if not isinstance(repos, list) or not repos:
        raise ConfigError(f"{path}: needs at least one [[repo]] table")
    data_dir = Path(_text(raw, "data_dir", path, str(DEFAULT_DATA_DIR))).expanduser()
    return NightlyConfig(_host(raw.get("host"), path), _repos(repos, path), data_dir)


def _host(table: Any, path: Path) -> HostConfig:
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: needs a [host] table")
    return HostConfig(
        ssh=_text(table, "ssh", path),
        checkout=_text(table, "checkout", path),
        env_file=_text(table, "env_file", path),
        work_root=_text(table, "work_root", path),
        model_prefix=_text(table, "model_prefix", path, DEFAULT_MODEL_PREFIX),
    )


def _repos(tables: list[Any], path: Path) -> tuple[RepoConfig, ...]:
    repos = tuple(_repo(table, path) for table in tables)
    names = [repo.name for repo in repos]
    if len(set(names)) != len(names):
        raise ConfigError(f"{path}: two [[repo]] tables share a name: {names}")
    return repos


def _repo(table: Any, path: Path) -> RepoConfig:
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: every [[repo]] must be a table")
    name = _text(table, "name", path)
    if not REPO_NAME.fullmatch(name):
        raise ConfigError(f"{path}: repo name {name!r} must be letters, digits, '.', '_' or '-'")
    return RepoConfig(
        name=name,
        project=_text(table, "project", path, name),
        sources=_texts(table, "sources", path),
        held_out=frozenset(_texts(table, "held_out", path)),
    )


def _text(table: Mapping[str, Any], key: str, path: Path, default: str | None = None) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{path}: {key!r} must be a non-empty string")
    return value


def _texts(table: Mapping[str, Any], key: str, path: Path) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{path}: {key!r} must be a list of non-empty strings")
    return tuple(value)
