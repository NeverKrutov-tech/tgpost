import hashlib
import re


WHITESPACE_RE = re.compile(r"\s+")
PUNCTUATION_RE = re.compile(r"[\u2010-\u2015]")
QUOTES_RE = re.compile(r"[\u00AB\u00BB\u2018\u2019\u201A\u201B\u201C\u201D\u201E]")
ALL_PUNCTUATION_RE = re.compile(r"[\u0021-\u002F\u003A-\u0040\u005B-\u0060\u007B-\u007E\u2010-\u2015\u2018-\u201D\u00AB\u00BB]")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = PUNCTUATION_RE.sub("-", text)
    text = QUOTES_RE.sub("\u0022", text)
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


def dedup_key(text: str) -> str:
    result = ALL_PUNCTUATION_RE.sub(" ", text)
    result = WHITESPACE_RE.sub(" ", result).strip()
    result = result.lower()
    return result
