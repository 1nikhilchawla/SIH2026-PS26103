#!/usr/bin/env python3
"""Mask personal identifiers in free text before it is stored, logged or sent
to the Laya sidecar.

Why: field remarks are typed by officials and can carry a contractor's phone
number, an officer's e-mail or an Aadhaar number. The Digital Personal Data
Protection Act, 2023 makes that personal data. ANUMAAN has no need for it -
the triage question is "what is delaying the project", not "who" - so it is
removed at the boundary and never reaches the audit log or the model.

What is masked (Indian formats first):
    Aadhaar     12 digits, first digit 2-9, optionally grouped 4-4-4
    PAN         AAAAA9999A
    phone       10-digit mobile starting 6-9, optional +91 / 0 prefix
    e-mail      name@domain.tld
    IFSC        AAAA0XXXXXX (bank branch code)
    long ids    any other run of 9+ digits (bank accounts, card numbers)

Deliberately NOT masked: 6-digit PAIMANA project codes, amounts with
separators ("Rs 1,234.56 crore"), dates, place and agency names. Masking those
would destroy the remark without protecting anyone.

This is pattern-based and will not catch everything (a name, an address).
It is a floor, not a guarantee - the remark box tells users not to enter
personal data at all.
"""
from __future__ import annotations

import re

_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("aadhaar", re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("ifsc", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("phone", re.compile(r"(?<![\d+])(?:\+91[ -]?|0)?[6-9]\d{9}(?!\d)")),
    ("long_number", re.compile(r"(?<!\d)\d{9,}(?!\d)")),
)


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return (masked_text, {kind: count}). Order matters: e-mail and the
    structured formats run before the generic digit rules."""
    counts: dict[str, int] = {}
    out = text
    for kind, pat in _PATTERNS:
        out, n = pat.subn(f"[{kind} removed]", out)
        if n:
            counts[kind] = n
    return out, counts
