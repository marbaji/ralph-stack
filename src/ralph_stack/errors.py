import hashlib
import re


_PATH_RE = re.compile(r"(/[\w./\-]+)")
_NUMBER_RE = re.compile(r"\b\d+\b")
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")


def normalize_error(msg: str) -> str:
    """Strip paths, numbers, and hex addresses so similar errors hash identically."""
    s = _PATH_RE.sub("<PATH>", msg)
    s = _HEX_RE.sub("<HEX>", s)
    s = _NUMBER_RE.sub("<N>", s)
    return s.strip()


def error_hash(msg: str) -> str:
    """Return a stable 16-char hex hash of the normalized error."""
    normalized = normalize_error(msg)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
