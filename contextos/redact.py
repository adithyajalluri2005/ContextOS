"""Hide secrets and personal details before a context is saved.

Each match is replaced by a short marker such as "[hidden: email]". Only the
number of hidden items of each kind is kept; the hidden text itself is never
stored, printed or returned.

The rules come from the first version of ContextOS (tag v0-export-design),
where they were tested on many made-up cases.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from contextos.context import Context

# Kinds, in the order they are shown to the reader.
PRIVATE_KEY = "private key"
URL_PASSWORD = "password in URL"
ANTHROPIC_KEY = "Anthropic key"
OPENAI_KEY = "OpenAI key"
AWS_KEY = "AWS key"
GITHUB_TOKEN = "GitHub token"
EMAIL = "email"
PHONE = "phone number"
KINDS = (PRIVATE_KEY, URL_PASSWORD, ANTHROPIC_KEY, OPENAI_KEY, AWS_KEY, GITHUB_TOKEN, EMAIL, PHONE)


def marker(kind: str) -> str:
    return f"[hidden: {kind}]"


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    # Builds the replacement from the match. Default: the whole match becomes the marker.
    replace: Callable[[re.Match[str]], str] | None = None
    # Extra check on a match; False keeps the text as it is.
    accept: Callable[[re.Match[str]], bool] | None = None


def _keep_prefix(m: re.Match[str]) -> str:
    """Keep group 1 (for example `aws_secret_access_key = `) and hide only the value."""
    return m.group(1) + marker(AWS_KEY)


def _url_password(m: re.Match[str]) -> str:
    return f"{m.group('start')}{marker(URL_PASSWORD)}@"


_IP = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
_DATE = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}")


def _looks_like_phone(m: re.Match[str]) -> bool:
    text = m.group(0)
    digits = sum(ch.isdigit() for ch in text)
    if not 10 <= digits <= 15:
        return False
    if _DATE.search(text) or _IP.fullmatch(text):
        return False
    # Plain long numbers (IDs, amounts) are kept unless they start with "+".
    return text.startswith("+") or bool(re.search(r"[\s().-]", text))


# Order matters: longer, more specific patterns run first, so for example an
# Anthropic key ("sk-ant-...") is not counted as an OpenAI key ("sk-...").
RULES: tuple[_Rule, ...] = (
    _Rule(
        PRIVATE_KEY,
        re.compile(
            r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----.*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----",
            re.DOTALL,
        ),
    ),
    # scheme://user:password@host  ->  scheme://user:[hidden: password in URL]@host
    _Rule(
        URL_PASSWORD,
        re.compile(r"(?P<start>\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:)[^\s/@]+@"),
        replace=_url_password,
    ),
    _Rule(ANTHROPIC_KEY, re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    _Rule(OPENAI_KEY, re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}")),
    _Rule(AWS_KEY, re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[A-Z0-9]{16}\b")),
    _Rule(
        AWS_KEY,
        re.compile(r"(?i)(aws_secret_access_key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"),
        replace=_keep_prefix,
    ),
    _Rule(GITHUB_TOKEN, re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})")),
    _Rule(EMAIL, re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    _Rule(
        PHONE,
        re.compile(r"(?<![\w.+/-])\+?\(?\d{1,4}\)?(?:[ .-]?\(?\d{2,5}\)?){1,5}(?![\w.]*\d)"),
        accept=_looks_like_phone,
    ),
)


def redact_text(text: str, counts: Counter[str] | None = None) -> str:
    """Return `text` with secrets replaced by markers. Adds what was hidden to `counts`."""
    for rule in RULES:

        def sub(m: re.Match[str], rule: _Rule = rule) -> str:
            if rule.accept and not rule.accept(m):
                return m.group(0)
            if counts is not None:
                counts[rule.kind] += 1
            return rule.replace(m) if rule.replace else marker(rule.kind)

        text = rule.pattern.sub(sub, text)
    return text


def _walk(value: Any, counts: Counter[str]) -> Any:
    if isinstance(value, str):
        return redact_text(value, counts)
    if isinstance(value, list):
        return [_walk(v, counts) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v, counts) for k, v in value.items()}
    return value


def redact_context(context: Context) -> Context:
    """A copy of `context` with every text field cleaned, and `redacted` set to the counts.

    The `id` is never changed. `redacted` is {} when nothing was found. Counts already
    on the context are kept and added to, so cleaning twice does not lose them.
    """
    counts: Counter[str] = Counter(context.redacted or {})
    data = context.model_dump(mode="python", exclude={"id", "redacted"})
    cleaned = _walk(data, counts)
    return Context.model_validate({**cleaned, "id": context.id, "redacted": ordered(counts)})


def ordered(counts: Counter[str]) -> dict[str, int]:
    """Counts as a plain dict in the fixed KINDS order, leaving out kinds with nothing hidden."""
    return {kind: counts[kind] for kind in KINDS if counts[kind]}


__all__ = ["KINDS", "RULES", "marker", "ordered", "redact_context", "redact_text"]
