from __future__ import annotations

from pathlib import Path


def wrapper_path() -> Path:
    """Return the absolute path to scripts/claude-ralph-wrapper.sh inside the
    installed ralph-stack package.

    Computed from __file__ so it is independent of the user's CWD. ralph-stack
    is distributed via `pip install -e` (see install.sh); scripts/ lives at the
    repo root alongside src/, so __file__.parent.parent.parent/scripts resolves
    correctly for the editable layout.
    """
    return (Path(__file__).parent.parent.parent / "scripts" / "claude-ralph-wrapper.sh").resolve()


def upsert_key(path: Path, key: str, value: str) -> bool:
    """Upsert a `key = value` line in a `.ralphex/config`-style file.

    Returns True if the file was changed (key added or value changed), False if
    the key already had that value. Creates the file if absent. Preserves
    comments (# ...) and blank lines verbatim. Tolerates CRLF input (the parser
    strips trailing \\r before comparing); writes LF on output.
    """
    existing = path.read_text() if path.exists() else ""
    new_line = f"{key} = {value}"
    lines = existing.splitlines() if existing else []
    out: list[str] = []
    found = False
    changed = False
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k == key:
                found = True
                if line.rstrip("\r") == new_line:
                    out.append(line)
                else:
                    out.append(new_line)
                    changed = True
                continue
        out.append(line)
    if not found:
        if out and out[-1].strip() != "":
            out.append("")
        out.append(new_line)
        changed = True
    if not changed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    return True


def upsert_keys(path: Path, pairs: dict[str, str]) -> list[str]:
    """Upsert multiple key/value pairs. Returns list of keys that changed."""
    changed: list[str] = []
    for key, value in pairs.items():
        if upsert_key(path, key, value):
            changed.append(key)
    return changed
