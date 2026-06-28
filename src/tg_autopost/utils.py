import hashlib
import re


WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    result = []
    prev_empty = False
    for line in lines:
        cleaned = WHITESPACE_RE.sub(" ", line).strip()
        if not cleaned:
            if not prev_empty:
                result.append("")
                prev_empty = True
        else:
            result.append(cleaned)
            prev_empty = False
    while result and not result[-1]:
        result.pop()
    return "\n".join(result)


def build_hash(text: str) -> str:
    normalized = normalize_text(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
