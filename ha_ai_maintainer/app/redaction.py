"""Redact values that should never appear in exported diagnostics."""

from __future__ import annotations

import re

REDACTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b(bearer|token|api[_-]?key|password|passwd|secret)"
            r"(\s*[:=]\s*)([^\s,;]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"), "[REDACTED_OPENAI_KEY]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        re.compile(
            r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
            r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
        ),
        "[REDACTED_IP]",
    ),
    (
        re.compile(
            r"(?i)\b(latitude|longitude|lat|lon|lng)"
            r"(\s*[:=]\s*)[-+]?\d{1,3}(?:\.\d+)?"
        ),
        r"\1\2[REDACTED_COORDINATE]",
    ),
    (
        re.compile(r"(?i)(https?://)([^/\s:@]+):([^@\s/]+)@"),
        r"\1[REDACTED_CREDENTIALS]@",
    ),
)


def redact_text(value: str) -> tuple[str, int]:
    """Return redacted text and the number of replacements."""

    redacted = value
    replacements = 0
    for pattern, replacement in REDACTION_RULES:
        redacted, count = pattern.subn(replacement, redacted)
        replacements += count
    return redacted, replacements
