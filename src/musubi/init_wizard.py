"""Interactive setup wizard for musubi.

Guides new users through environment check → demo or real notes →
custom concepts → cron setup. Called via `musubi init`.
"""
from __future__ import annotations

import importlib.resources
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from musubi import __version__
from musubi.config import load_config

# ── Colors ──────────────────────────────────────────────────────────────

ANSI = {
    "reset": "\033[0m", "dim": "\033[2m", "bold": "\033[1m",
    "cyan": "\033[36m", "yellow": "\033[33m", "green": "\033[32m",
    "red": "\033[31m",
}
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text: str, color: str) -> str:
    return f"{ANSI[color]}{text}{ANSI['reset']}" if USE_COLOR else text


def _ask(prompt: str, default: str = "") -> str:
    """Prompt with a default value. Returns stripped input or default."""
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return ans or default


def _confirm(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        ans = input(f"  {prompt} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    if not ans:
        return default
    return ans in ("y", "yes")


def _menu(prompt: str, options: list[str]) -> int:
    """Show a numbered menu. Returns 0-based index of selected option."""
    print()
    for i, opt in enumerate(options, 1):
        print(f"    [{i}] {opt}")
    print()
    while True:
        try:
            raw = input(f"  {prompt}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(c(f"    Enter 1-{len(options)}", "yellow"))


# ── Environment checks ─────────────────────────────────────────────────


def _check_env() -> dict[str, bool]:
    """Run environment checks and print results."""
    print()
    print(c("  Checking environment...", "dim"))

    checks: dict[str, bool] = {}

    # Python version
    v = sys.version_info
    ok = v >= (3, 11)
    checks["python"] = ok
    icon = c("✓", "green") if ok else c("✗", "red")
    print(f"    {icon} Python {v.major}.{v.minor}.{v.micro}")

    # musubi itself
    print(f"    {c('✓', 'green')} musubi {__version__}")
    checks["musubi"] = True

    # qmd
    qmd = shutil.which("qmd")
    checks["qmd"] = qmd is not None
    if qmd:
        print(f"    {c('✓', 'green')} qmd found at {qmd}")
    else:
        print(f"    {c('·', 'dim')} qmd not found {c('(optional — filesystem mode works fine)', 'dim')}")

    # networkx (should always be present since it's a dependency)
    try:
        import networkx  # noqa: F401
        print(f"    {c('✓', 'green')} networkx")
        checks["networkx"] = True
    except ImportError:
        print(f"    {c('✗', 'red')} networkx not installed")
        checks["networkx"] = False

    return checks


# ── Demo flow ──────────────────────────────────────────────────────────


def _find_demo_notes() -> Path | None:
    """Locate the bundled demo notes directory."""
    # 1. Check package data (works after pip install)
    try:
        pkg = importlib.resources.files("musubi") / "demo-notes"
        # importlib.resources returns a Traversable; check if it's a real dir
        pkg_path = Path(str(pkg))
        if pkg_path.is_dir():
            return pkg_path
    except (TypeError, FileNotFoundError):
        pass

    # 2. Check relative to this file (development install / editable mode)
    dev = Path(__file__).parent.parent.parent / "examples" / "demo-notes"
    if dev.is_dir():
        return dev

    return None


def _run_demo() -> bool:
    """Build from demo notes and show results. Returns True if successful."""
    demo = _find_demo_notes()
    if demo is None:
        print(c("    Demo notes not found. Run from the musubi repo directory,", "red"))
        print(c("    or reinstall with: uv tool install --force .", "red"))
        return False

    print()
    print(c(f"  Building from demo notes ({demo})...", "dim"))

    from musubi.builder import build as do_build
    cfg = load_config()
    cfg.ensure_dirs()

    try:
        summary = do_build(cfg, source=demo, verbose=False)
    except Exception as e:
        print(c(f"    Build failed: {e}", "red"))
        return False

    n = summary["nodes"]
    e = summary["concept_edges"] + summary.get("embedding_edges", 0)
    iso = summary["isolated"]
    print(f"    {c('✓', 'green')} {n} docs, {e} edges, {iso} isolated")
    print()
    print(c("  Try these commands:", "cyan"))
    print(f"    musubi stats")
    print(f"    musubi neighbors \"vllm\"")
    print(f"    musubi cold")
    print()
    print(c("  Ready to use your own notes? Run:", "dim"))
    print(f"    musubi init")
    return True


# ── Own notes flow ─────────────────────────────────────────────────────


def _run_own_notes() -> bool:
    """Guide the user through building from their own notes."""
    print()
    notes_path = _ask("Path to your notes directory", "~/notes")
    notes_dir = Path(os.path.expanduser(notes_path))

    if not notes_dir.is_dir():
        print(c(f"    Directory not found: {notes_dir}", "red"))
        return False

    # Count markdown files
    md_count = sum(1 for _ in notes_dir.rglob("*.md"))
    mdx_count = sum(1 for _ in notes_dir.rglob("*.mdx"))
    total = md_count + mdx_count

    if total == 0:
        print(c(f"    No *.md or *.mdx files found in {notes_dir}", "red"))
        return False

    print(f"    Found {c(str(total), 'cyan')} markdown files")

    # Count subdirectories (potential collections)
    subdirs = [d.name for d in notes_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if subdirs:
        print(f"    Collections: {', '.join(subdirs[:8])}{' ...' if len(subdirs) > 8 else ''}")

    print()
    print(c("  Building graph...", "dim"))

    from musubi.builder import build as do_build
    cfg = load_config()
    cfg.ensure_dirs()

    try:
        summary = do_build(cfg, source=notes_dir, verbose=False)
    except Exception as e:
        print(c(f"    Build failed: {e}", "red"))
        return False

    n = summary["nodes"]
    e = summary["concept_edges"] + summary.get("embedding_edges", 0)
    iso = summary["isolated"]
    iso_pct = 100 * iso / max(n, 1)

    print(f"    {c('✓', 'green')} {n} docs, {e} edges, {iso} isolated ({iso_pct:.0f}%)")

    if iso_pct > 30:
        print()
        print(c("  ⚠ High isolation rate.", "yellow"))
        print(c("    Your notes likely use domain-specific terms that aren't in", "yellow"))
        print(c("    the default concept dictionary. Adding a custom concepts", "yellow"))
        print(c("    file (next step) will fix this.", "yellow"))

    # Custom concepts
    print()
    if _confirm("Create a custom concepts file for your domain?"):
        _setup_concepts()

        if _confirm("Rebuild with custom concepts?"):
            print(c("  Rebuilding...", "dim"))
            cfg2 = load_config()  # reload to pick up new concepts file
            try:
                s2 = do_build(cfg2, source=notes_dir, verbose=False)
                e2 = s2["concept_edges"] + s2.get("embedding_edges", 0)
                iso2 = s2["isolated"]
                delta_e = e2 - e
                delta_iso = iso - iso2
                print(f"    {c('✓', 'green')} edges: {e} → {e2} ({'+' if delta_e >= 0 else ''}{delta_e})")
                print(f"    {c('✓', 'green')} isolated: {iso} → {iso2} ({'-' if delta_iso >= 0 else '+'}{abs(delta_iso)})")
            except Exception as ex:
                print(c(f"    Rebuild failed: {ex}", "red"))

    # Cron
    print()
    if _confirm("Set up weekly auto-rebuild?"):
        _setup_cron(notes_dir)

    return True


# ── qmd flow ───────────────────────────────────────────────────────────


def _run_qmd() -> bool:
    """Build from the qmd SQLite index."""
    cfg = load_config()

    if not cfg.qmd_db.exists():
        print(c(f"    qmd index not found at {cfg.qmd_db}", "red"))
        print(c("    Run: qmd update", "dim"))
        return False

    print()
    print(c(f"  Building from qmd index ({cfg.qmd_db})...", "dim"))

    from musubi.builder import build as do_build
    cfg.ensure_dirs()

    try:
        summary = do_build(cfg, verbose=False)
    except Exception as e:
        print(c(f"    Build failed: {e}", "red"))
        return False

    n = summary["nodes"]
    e = summary["concept_edges"] + summary.get("embedding_edges", 0)
    iso = summary["isolated"]
    print(f"    {c('✓', 'green')} {n} docs, {e} edges, {iso} isolated")
    print(c("    (includes embedding fallback for isolated nodes)", "dim"))

    # Custom concepts
    print()
    if _confirm("Create a custom concepts file for your domain?"):
        _setup_concepts()

    # Cron
    print()
    if _confirm("Set up weekly auto-rebuild?"):
        _setup_cron_qmd()

    return True


# ── Helpers ─────────────────────────────────────────────────────────────


def _setup_concepts() -> None:
    """Create or open the user concepts file."""
    cfg = load_config()
    concepts_dir = cfg.concepts_file.parent if cfg.concepts_file else Path(
        os.path.expanduser("~/.config/musubi")
    )
    concepts_file = concepts_dir / "concepts.txt"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    if concepts_file.exists():
        print(f"    Concepts file already exists: {concepts_file}")
        print(c("    Edit it to add your domain terms, then rebuild.", "dim"))
        return

    template = """# Musubi custom concepts — your domain vocabulary
# One term per line. Lines starting with # are comments.
# After editing, rebuild: musubi build --source ~/your-notes/

# === Add your terms below ===

# Product / project names
# my-product
# internal-api

# Domain vocabulary
# (examples for different domains)

# Finance:
# black-scholes
# portfolio rebalancing
# sharpe ratio

# DevOps:
# terraform
# ansible
# prometheus

# ML/AI:
# fine-tuning
# rlhf
# lora
"""
    concepts_file.write_text(template, encoding="utf-8")
    print(f"    {c('✓', 'green')} Created: {concepts_file}")
    print(c("    Edit it to add terms specific to your work.", "dim"))

    # Try to open in editor
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor and _confirm(f"Open in {editor}?", default=False):
        subprocess.run([editor, str(concepts_file)])


def _setup_cron(notes_dir: Path) -> None:
    """Add a crontab entry for weekly rebuild (filesystem mode)."""
    musubi_bin = shutil.which("musubi") or "musubi"
    entry = f'17 2 * * 0 {musubi_bin} build --source {notes_dir} >> /tmp/musubi-weekly.log 2>&1'
    _add_cron_entry(entry)


def _setup_cron_qmd() -> None:
    """Add a crontab entry for weekly rebuild (qmd mode)."""
    musubi_bin = shutil.which("musubi") or "musubi"
    qmd_bin = shutil.which("qmd") or "qmd"
    entry = f'17 2 * * 0 {qmd_bin} update > /tmp/musubi-weekly.log 2>&1 && {musubi_bin} build >> /tmp/musubi-weekly.log 2>&1'
    _add_cron_entry(entry)


def _add_cron_entry(entry: str) -> None:
    """Append a cron entry if it doesn't already exist."""
    if platform.system() == "Windows":
        print(c("    Cron is not available on Windows.", "yellow"))
        print(c(f"    Use Task Scheduler with: {entry.split('0 ', 1)[-1]}", "dim"))
        return

    try:
        existing = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        ).stdout
    except FileNotFoundError:
        print(c("    crontab not found.", "yellow"))
        return

    if "musubi" in existing:
        print(c("    Crontab already has a musubi entry. Skipping.", "dim"))
        return

    new_crontab = existing.rstrip("\n") + f"\n\n# musubi weekly graph rebuild\n{entry}\n"
    proc = subprocess.run(
        ["crontab", "-"], input=new_crontab, text=True, capture_output=True
    )
    if proc.returncode == 0:
        print(f"    {c('✓', 'green')} Added weekly rebuild to crontab (Sunday 02:17)")
    else:
        print(c(f"    Failed to update crontab: {proc.stderr}", "red"))


# ── Main ────────────────────────────────────────────────────────────────


def run_init() -> int:
    """Entry point for `musubi init`."""
    print()
    print(c("┌─────────────────────────────────────────┐", "cyan"))
    print(c("│         ◇ Musubi Setup                  │", "cyan"))
    print(c("└─────────────────────────────────────────┘", "cyan"))

    checks = _check_env()

    if not checks.get("networkx"):
        print(c("\n  networkx is required. Install: pip install musubi", "red"))
        return 1

    # Build the menu based on what's available
    options = [
        "Try the demo first (20 sample notes included)",
        "Use my own notes directory",
    ]
    if checks.get("qmd"):
        options.append("Use my qmd index (richer graph with embeddings)")

    choice = _menu("Choose a source", options)

    if choice == 0:
        ok = _run_demo()
    elif choice == 1:
        ok = _run_own_notes()
    else:
        ok = _run_qmd()

    if ok:
        cfg = load_config()
        print()
        print(c("  ┌─────────────────────────────────────┐", "green"))
        print(c("  │       ✓ Setup complete!              │", "green"))
        print(c("  └─────────────────────────────────────┘", "green"))
        print()
        print(f"    Graph:    {cfg.graph_path}")
        if cfg.concepts_file and cfg.concepts_file.exists():
            print(f"    Concepts: {cfg.concepts_file}")
        print()
        print(c("  Next steps:", "cyan"))
        print(f"    musubi stats              # graph overview")
        print(f"    musubi neighbors \"X\"       # find related notes")
        print(f"    musubi cold               # find stale notes")
        print()

    return 0 if ok else 1
