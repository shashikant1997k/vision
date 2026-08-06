"""Grammar-constrained CTC decoding: NFA correctness, error recovery, safety."""

from __future__ import annotations

import re

import numpy as np
import pytest

from vis.tools.constrained_decode import RegexNFA, decode, escape, pattern_for_field

ITOS = ["<blank>"] + list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/.() ")

PATTERNS = [
    r"\d{2}/\d{4}",
    r"EXP\. \d{2}/\d{4}",
    r"[A-Z]{2}\d{4}",
    r"\d+\.\d{2}",
    r"(MFG|EXP)\.\d{2}",
    r"B\.No\.[A-Z0-9]{5,10}",
    r"[A-Z]?\d*",
    r"AB|CD|EF",
    r"\(INCL\. OF ALL TAXES\)",
]
SAMPLES = [
    "10/2026", "1/2026", "10/20265", "AB/2026", "EXP. 10/2026", "EXP 10/2026",
    "AB1234", "A81234", "AB123", "120.00", "1.5", "0120.99", "MFG.01", "EXP.99",
    "XYZ.01", "B.No.TEST12345", "B.No.AB", "A123", "", "AB", "CD", "XY",
    "(INCL. OF ALL TAXES)", "(INCL. OF ALL TAXES", "00/0000",
]


def nfa_matches(pattern: str, text: str) -> bool:
    nfa = RegexNFA(pattern)
    states = nfa.start()
    for ch in text:
        states = nfa.step(states, ch)
        if not states:
            return False
    return nfa.accepts(states)


@pytest.mark.parametrize("pattern", PATTERNS)
def test_nfa_agrees_with_python_re(pattern):
    """Our incremental NFA must accept exactly what `re.fullmatch` accepts."""
    for text in SAMPLES:
        assert nfa_matches(pattern, text) == (re.fullmatch(pattern, text) is not None), (
            f"{pattern!r} vs {text!r}"
        )


def test_nfa_rejects_dead_prefix_early():
    nfa = RegexNFA(r"\d{2}/\d{4}")
    states = nfa.step(nfa.start(), "A")
    assert not states  # 'A' can never start this field


def test_bad_pattern_raises():
    for bad in (r"(unclosed", r"[unclosed", "trailing\\"):
        with pytest.raises(ValueError):
            RegexNFA(bad)


# ---- decoding ------------------------------------------------------------
def _logits(text: str, corrupt_at: int | None = None, wrong: str = ".") -> np.ndarray:
    """Synthetic CTC logits that spell `text`, optionally with one character
    losing narrowly to a confusable."""
    T, C = len(text) * 2, len(ITOS)
    lg = np.full((T, C), -6.0)
    lg[:, 0] = 0.0
    for i, ch in enumerate(text):
        t, cid = i * 2, ITOS.index(ch)
        lg[t, :] = -6.0
        lg[t, cid] = 3.0
        if corrupt_at == i:
            lg[t, cid] = 2.0
            lg[t, ITOS.index(wrong)] = 2.6
    return lg


def test_clean_decode_matches_greedy():
    text, conf = decode(_logits("10/2026"), ITOS)
    assert text == "10/2026"
    assert conf > 0.5


def test_grammar_recovers_a_character_error():
    """The headline behaviour: an illegal character cannot win."""
    lg = _logits("10/2026", corrupt_at=2, wrong=".")
    assert decode(lg, ITOS)[0] == "10.2026"                      # unconstrained fails
    assert decode(lg, ITOS, pattern=r"\d{2}/\d{4}")[0] == "10/2026"


def test_charset_constraint_recovers_too():
    lg = _logits("10/2026", corrupt_at=2, wrong=".")
    assert decode(lg, ITOS, charset="0123456789/")[0] == "10/2026"


def test_confidence_separates_right_from_wrong_grammar():
    """SAFETY: a constrained decode always emits a legal string, so confidence —
    not the text — is what distinguishes a real read from a forced one."""
    lg = _logits("10/2026")
    _, good = decode(lg, ITOS, pattern=r"\d{2}/\d{4}")
    _, bad = decode(lg, ITOS, pattern=r"\(INCL\. OF ALL TAXES\)")
    assert good > 0.5 and bad < 0.05 and good > bad * 10


def test_impossible_grammar_falls_back_not_crashes():
    """A damaged print must still yield a reading for the operator."""
    text, _ = decode(_logits("10/2026"), ITOS, pattern=r"ZZZZ")
    assert isinstance(text, str)


def test_beam_never_emits_illegal_text():
    lg = _logits("AB1234", corrupt_at=0, wrong="1")
    text, _ = decode(lg, ITOS, pattern=r"[A-Z]{2}\d{4}")
    assert re.fullmatch(r"[A-Z]{2}\d{4}", text)


# ---- config plumbing -----------------------------------------------------
def test_pattern_from_regex_config():
    assert pattern_for_field({"match": "regex", "pattern": r"\d+"}) == r"\d+"


def test_pattern_from_exact_expected_is_escaped():
    got = pattern_for_field({"match": "exact", "expected": "EXP. 10/2026"})
    assert re.fullmatch(got, "EXP. 10/2026")
    assert not re.fullmatch(got, "EXP. 11/2026")


def test_no_grammar_when_config_has_none():
    assert pattern_for_field(None) is None
    assert pattern_for_field({"match": "contains", "expected": "x"}) is None


def test_escape_handles_regex_metacharacters():
    literal = "M.R.P Rs. 000.00 (x)"
    assert re.fullmatch(escape(literal), literal)
