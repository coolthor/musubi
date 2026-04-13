"""Runtime configuration for musubi.

Everything here is overridable via environment variables so the package has
zero hardcoded user paths. Defaults assume a conventional layout under the
user's home directory, but nothing else in the package depends on those
specific paths.

Environment variables
---------------------
MUSUBI_GRAPH_PATH     Path to the serialized graph JSON (node_link_data format).
                      Default: ~/.local/share/musubi/graph.json
MUSUBI_QMD_DB         Path to the @tobilu/qmd SQLite index.
                      Default: ~/.cache/qmd/index.sqlite
MUSUBI_QMD_BIN        Path to the `qmd` binary used by `musubi search`.
                      Default: whatever `qmd` resolves to on PATH.
MUSUBI_CONCEPTS_FILE  Optional extra concept list (one term per line, # for
                      comments). Merged with the built-in default dictionary.
                      Default: ~/.config/musubi/concepts.txt if present.
MUSUBI_LOG_DIR        Where musubi writes its own logs (regen, etc.).
                      Default: ~/.local/state/musubi/
MUSUBI_WATCH_DIRS     Colon-separated list of directories to monitor for
                      freshness. If any .md file in these dirs is newer than
                      the graph, auto-rebuild triggers on next query. Useful
                      for auto-memory directories or note sources outside qmd.
                      Default: none.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def _env_path(var: str, default: Path) -> Path:
    raw = os.environ.get(var)
    return Path(os.path.expanduser(raw)) if raw else default


def _xdg_data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))


def _xdg_config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"))


def _xdg_state() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"))


def _xdg_cache() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"))


@dataclass(frozen=True)
class Config:
    graph_path: Path
    qmd_db: Path
    qmd_bin: str
    concepts_file: Path | None
    log_dir: Path
    output_dir: Path

    def ensure_dirs(self) -> None:
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    data_dir = _xdg_data() / "musubi"
    cfg_dir = _xdg_config() / "musubi"
    state_dir = _xdg_state() / "musubi"

    graph_path = _env_path("MUSUBI_GRAPH_PATH", data_dir / "graph.json")
    qmd_db = _env_path("MUSUBI_QMD_DB", _xdg_cache() / "qmd" / "index.sqlite")
    qmd_bin = os.environ.get("MUSUBI_QMD_BIN") or shutil.which("qmd") or "qmd"

    # Concepts file: explicit env var > default path if it exists > None
    raw_concepts = os.environ.get("MUSUBI_CONCEPTS_FILE")
    if raw_concepts:
        concepts_file: Path | None = Path(os.path.expanduser(raw_concepts))
    else:
        default_concepts = cfg_dir / "concepts.txt"
        concepts_file = default_concepts if default_concepts.exists() else None

    log_dir = _env_path("MUSUBI_LOG_DIR", state_dir)

    return Config(
        graph_path=graph_path,
        qmd_db=qmd_db,
        qmd_bin=qmd_bin,
        concepts_file=concepts_file,
        log_dir=log_dir,
        output_dir=data_dir,
    )
