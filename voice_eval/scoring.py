"""Scoring: word error rate and key-term accuracy.

Key-term accuracy is the number that decides the evaluation (numbers,
exercise names, symptoms). WER is the secondary, overall-quality signal.

Hinglish caveat: a model may write a Hindi word in Devanagari ("दर्द") where
the reference has it in Roman ("dard"). WER counts that as wrong; key terms
handle it by listing both spellings as alternatives — see references.example.csv.
"""
from __future__ import annotations

import re
import unicodedata

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split())}


def normalize(text: str) -> str:
    """Lowercase, Devanagari digits -> ASCII, punctuation/symbols -> spaces,
    "2km" -> "2 km", English number words -> digits.

    Punctuation is stripped by Unicode category rather than `\\W`, because
    Devanagari vowel signs and the virama are combining marks that `\\W`
    would strip, mangling every Hindi word.
    """
    text = text.lower().translate(_DEVANAGARI_DIGITS)
    text = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in text)
    text = re.sub(r"(\d)([^\d\s])", r"\1 \2", text)
    text = re.sub(r"([^\d\s])(\d)", r"\1 \2", text)
    return " ".join(_words_to_digits(text.split()))


def _words_to_digits(tokens: list[str]) -> list[str]:
    out, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _TENS:
            value = _TENS[tok]
            if i + 1 < len(tokens) and tokens[i + 1] in _UNITS and 0 < _UNITS[tokens[i + 1]] < 10:
                value += _UNITS[tokens[i + 1]]
                i += 1
            out.append(str(value))
        elif tok in _UNITS:
            out.append(str(_UNITS[tok]))
        else:
            out.append(tok)
        i += 1
    return out


def wer(reference: str, hypothesis: str) -> float:
    """Word-level edit distance / reference length, on normalized text."""
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def key_term_hits(hypothesis: str, key_terms: str) -> tuple[int, int, list[str]]:
    """`key_terms` is the references.csv cell: terms separated by `|`, each
    with alternative spellings separated by `/` (e.g. "20|squats|dard/दर्द").
    A term counts as heard if any alternative appears as whole words.
    Returns (hits, total, missed terms)."""
    terms = [t for t in (key_terms or "").split("|") if t.strip()]
    padded = f" {normalize(hypothesis)} "
    missed = []
    for term in terms:
        alternatives = [normalize(a) for a in term.split("/") if a.strip()]
        if not any(f" {a} " in padded for a in alternatives):
            missed.append(term)
    return len(terms) - len(missed), len(terms), missed
