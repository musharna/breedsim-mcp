"""Score one benchmark answer against its question's theory value and band.

Every run ends its reply with ``ANSWER: <number>`` (or ``ANSWER: UNKNOWN``);
the verdict is decided from that line alone, so the same reply always scores
the same way. Verdicts:

- ``right``: the number is within the question's stated band of the theory
  value (``truth.half_width``, which the question text states as a percent).
- ``wrong``: a number outside the band, or a value with no number in it.
- ``declined``: ``ANSWER: UNKNOWN``.
- ``no_answer``: no ``ANSWER:`` line at all (a format failure, kept apart so it
  is never silently counted as either of the others).

Legitimate other spellings of the same number are read as that number: a
percent sign divides by 100 (a variance "as a fraction of the founder
variance" may be written 79%), a Unicode minus is a minus, and thousands
separators are dropped. Every answer also carries ``rel_error``, so how far a
wrong answer missed is in the log rather than inferred from its verdict.
"""

from __future__ import annotations

import re
from typing import Any

_ANSWER_RE = re.compile(r"^[\s>*_`#-]*answer[*_`]*\s*:\s*(.*?)\s*$", re.IGNORECASE)
_UNKNOWN = {"UNKNOWN", "UNKNOWN.", "N/A", "NONE"}
# A signed decimal, optional exponent, optional percent sign right after it.
_NUMBER_RE = re.compile(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(%?)")


def extract(reply: str) -> str | None:
    """The value on the reply's last ``ANSWER:`` line, unwrapped; None if none."""
    found = None
    for line in reply.splitlines():
        m = _ANSWER_RE.match(line)
        if m:
            found = m.group(1)
    if found is None:
        return None
    return re.sub(r"</?answer>", "", found, flags=re.IGNORECASE).strip(" \t*_`")


def number(value: str) -> float | None:
    """The first number in the value, as a float; None if there is none."""
    v = value.replace("−", "-").replace("–", "-")
    v = re.sub(r"(?<=\d),(?=\d{3}\b)", "", v)
    m = _NUMBER_RE.search(v)
    if not m:
        return None
    x = float(m.group(1))
    return x / 100 if m.group(2) == "%" else x


def score(question: dict[str, Any], reply: str) -> dict[str, Any]:
    value = extract(reply)
    if value is None:
        return {
            "verdict": "no_answer",
            "value": None,
            "number": None,
            "rel_error": None,
        }
    if value.upper().strip() in _UNKNOWN:
        return {
            "verdict": "declined",
            "value": value,
            "number": None,
            "rel_error": None,
        }
    truth = question["truth"]
    x = number(value)
    if x is None:
        return {"verdict": "wrong", "value": value, "number": None, "rel_error": None}
    right = abs(x - truth["value"]) <= truth["half_width"] + 1e-12
    rel = (x - truth["value"]) / abs(truth["value"]) if truth["value"] else None
    return {
        "verdict": "right" if right else "wrong",
        "value": value,
        "number": x,
        "rel_error": None if rel is None else round(rel, 4),
    }
