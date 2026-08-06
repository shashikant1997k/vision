"""Grammar-constrained CTC decoding — the cheapest large accuracy win.

Greedy CTC decoding picks the best character at each frame independently, so a
single confusable character (O/0, B/8, 5/S, 1/I) breaks the whole field. Because
a field fails when *any* character fails, character accuracy compounds brutally:
at 93.5% per character a ten-character field is only 0.935^10 ~= 51%.

But industrial fields are not free text — they have grammar. ``EXP. 10/2026`` is
``EXP\\. \\d{2}/\\d{4}``; an MRP is ``\\d+\\.\\d{2}``. If the decoder may only emit
characters that keep the field grammatically legal, most single-character errors
are simply not expressible and the correct character wins by default.

This module does prefix beam search over the CTC logits where every beam carries
the state of a small regex automaton; a character is only considered if it keeps
that automaton alive, and a beam only finishes if the automaton accepts.

    decode(logits, itos)                        # unconstrained (beam > greedy)
    decode(logits, itos, pattern=r"\\d{2}/\\d{4}")   # grammar-constrained
    decode(logits, itos, charset="0123456789/")     # charset-constrained

The regex subset is deliberately small (literals, ``.``, classes, escapes,
groups, alternation, ``* + ? {n,m}``) — everything pharma field masks need, with
no catastrophic backtracking because it runs as an NFA state set.

.. warning::
   **A constrained decode always returns a grammar-legal string.** With a fully
   literal grammar it will emit the expected text even from a blank or wrong
   print, so the decoded *text* alone can never be the pass/fail criterion —
   the returned **confidence must be thresholded** (and for OCV, checked against
   ``ocv_score.verify``). Measured on the real blister golden set, the
   separation is wide: correct grammar on the right crop scores ~0.995, while a
   mismatched grammar or a blank crop scores ~0.001. Never wire this decoder to
   a tool that ignores confidence.

Measured on the 96-crop real blister golden set (same harness, same model):
greedy 20.8% field accuracy -> constrained 97.9%, at ~3.8 ms/field.
"""

from __future__ import annotations

import numpy as np

NEG_INF = -1e30
BLANK = 0


# --------------------------------------------------------------------------
# A small regex -> NFA (Thompson construction). We need *incremental prefix
# feasibility*, which Python's `re` cannot answer ("could this prefix still
# match?"), so we keep an explicit state set and step it per character.
# --------------------------------------------------------------------------
class _Frag:
    """NFA fragment: a start state and the set of states it can dangle into."""

    __slots__ = ("start", "outs")

    def __init__(self, start: int, outs: list[tuple[int, int]]) -> None:
        self.start = start
        self.outs = outs  # (state, slot) pairs waiting to be patched


class RegexNFA:
    """Thompson NFA supporting the subset needed for field masks."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        # transitions[i] = (kind, payload, next1, next2)
        #   kind 'c' = char predicate (payload = matcher), 'e' = epsilon split
        #   kind 'm' = match/accept
        self._trans: list[list] = []
        self._pos = 0
        frag = self._parse_alt(pattern)
        accept = self._add(["m", None, -1, -1])
        self._patch(frag.outs, accept)
        self._start = frag.start
        self.accept = accept

    # ---- construction helpers -------------------------------------------
    def _add(self, node: list) -> int:
        self._trans.append(node)
        return len(self._trans) - 1

    def _patch(self, outs: list[tuple[int, int]], target: int) -> None:
        for state, slot in outs:
            self._trans[state][2 + slot] = target

    # ---- recursive-descent parser ---------------------------------------
    def _peek(self) -> str | None:
        return self.pattern[self._pos] if self._pos < len(self.pattern) else None

    def _parse_alt(self, _pattern: str = "") -> _Frag:
        frag = self._parse_concat()
        while self._peek() == "|":
            self._pos += 1
            right = self._parse_concat()
            split = self._add(["e", None, frag.start, right.start])
            frag = _Frag(split, frag.outs + right.outs)
        return frag

    def _parse_concat(self) -> _Frag:
        frag: _Frag | None = None
        while (ch := self._peek()) is not None and ch not in "|)":
            piece = self._parse_repeat()
            if frag is None:
                frag = piece
            else:
                self._patch(frag.outs, piece.start)
                frag = _Frag(frag.start, piece.outs)
        if frag is None:  # empty alternative, e.g. "(a|)"
            s = self._add(["e", None, -1, -1])
            frag = _Frag(s, [(s, 0), (s, 1)])
        return frag

    def _parse_repeat(self) -> _Frag:
        atom = self._parse_atom()
        while (ch := self._peek()) in ("*", "+", "?", "{"):
            if ch == "*":
                self._pos += 1
                split = self._add(["e", None, atom.start, -1])
                self._patch(atom.outs, split)
                atom = _Frag(split, [(split, 1)])
            elif ch == "+":
                self._pos += 1
                split = self._add(["e", None, atom.start, -1])
                self._patch(atom.outs, split)
                atom = _Frag(atom.start, [(split, 1)])
            elif ch == "?":
                self._pos += 1
                split = self._add(["e", None, atom.start, -1])
                atom = _Frag(split, atom.outs + [(split, 1)])
            else:  # {n} / {n,} / {n,m} — expanded by re-parsing the atom text
                atom = self._parse_counted(atom)
        return atom

    def _parse_counted(self, atom: _Frag) -> _Frag:
        close = self.pattern.find("}", self._pos)
        if close < 0:
            raise ValueError(f"unterminated {{ in pattern {self.pattern!r}")
        body = self.pattern[self._pos + 1 : close]
        atom_src = self._last_atom_src
        self._pos = close + 1
        lo, _, hi_s = body.partition(",")
        lo_n = int(lo or 0)
        hi_n = None if (_ and not hi_s) else int(hi_s or lo_n)
        # build lo_n mandatory copies then (hi-lo) optional ones (or a star)
        parts: list[_Frag] = []
        for _i in range(lo_n):
            parts.append(atom if not parts and _i == 0 else self._reparse(atom_src))
        if hi_n is None:
            tail = self._reparse(atom_src)
            split = self._add(["e", None, tail.start, -1])
            self._patch(tail.outs, split)
            parts.append(_Frag(split, [(split, 1)]))
        else:
            for _i in range(hi_n - lo_n):
                opt = self._reparse(atom_src)
                split = self._add(["e", None, opt.start, -1])
                parts.append(_Frag(split, opt.outs + [(split, 1)]))
        if not parts:  # {0} — matches empty
            s = self._add(["e", None, -1, -1])
            return _Frag(s, [(s, 0), (s, 1)])
        frag = parts[0]
        for nxt in parts[1:]:
            self._patch(frag.outs, nxt.start)
            frag = _Frag(frag.start, nxt.outs)
        return frag

    def _reparse(self, src: str) -> _Frag:
        """Build another copy of an atom (quantifier expansion)."""
        saved_pattern, saved_pos = self.pattern, self._pos
        self.pattern, self._pos = src, 0
        frag = self._parse_atom()
        self.pattern, self._pos = saved_pattern, saved_pos
        return frag

    _last_atom_src = ""

    def _parse_atom(self) -> _Frag:
        start_pos = self._pos
        ch = self._peek()
        if ch is None:
            raise ValueError(f"unexpected end of pattern {self.pattern!r}")
        if ch == "(":
            self._pos += 1
            if self.pattern[self._pos : self._pos + 2] == "?:":
                self._pos += 2
            frag = self._parse_alt()
            if self._peek() != ")":
                raise ValueError(f"unbalanced ( in pattern {self.pattern!r}")
            self._pos += 1
        elif ch == "[":
            frag = self._char_state(self._parse_class())
        elif ch == "\\":
            self._pos += 1
            esc = self._peek()
            if esc is None:
                raise ValueError(f"trailing backslash in {self.pattern!r}")
            self._pos += 1
            frag = self._char_state(_escape_matcher(esc))
        elif ch == ".":
            self._pos += 1
            frag = self._char_state(lambda c: True)
        else:
            self._pos += 1
            frag = self._char_state(lambda c, want=ch: c == want)
        self._last_atom_src = self.pattern[start_pos : self._pos]
        return frag

    def _char_state(self, matcher) -> _Frag:
        s = self._add(["c", matcher, -1, -1])
        return _Frag(s, [(s, 0)])

    def _parse_class(self):
        self._pos += 1  # consume '['
        negate = self._peek() == "^"
        if negate:
            self._pos += 1
        items: list = []
        while (ch := self._peek()) is not None and ch != "]":
            if ch == "\\":
                self._pos += 1
                esc = self._peek()
                self._pos += 1
                items.append(_escape_matcher(esc))
                continue
            self._pos += 1
            if self._peek() == "-" and self.pattern[self._pos + 1 : self._pos + 2] not in ("]", ""):
                self._pos += 1
                hi = self._peek()
                self._pos += 1
                items.append(lambda c, lo=ch, hi=hi: lo <= c <= hi)
            else:
                items.append(lambda c, want=ch: c == want)
        if self._peek() != "]":
            raise ValueError(f"unbalanced [ in pattern {self.pattern!r}")
        self._pos += 1

        def matcher(c: str) -> bool:
            hit = any(m(c) for m in items)
            return (not hit) if negate else hit

        return matcher

    # ---- simulation ------------------------------------------------------
    def _closure(self, states: frozenset[int]) -> frozenset[int]:
        out, stack = set(), list(states)
        while stack:
            s = stack.pop()
            if s in out or s < 0:
                continue
            out.add(s)
            if self._trans[s][0] == "e":
                stack.extend(x for x in self._trans[s][2:4] if x >= 0)
        return frozenset(out)

    def start(self) -> frozenset[int]:
        return self._closure(frozenset([self._start]))

    def step(self, states: frozenset[int], ch: str) -> frozenset[int]:
        """States reachable after consuming ``ch``; empty = prefix is dead."""
        nxt = set()
        for s in states:
            kind, matcher, n1, _n2 = self._trans[s]
            if kind == "c" and matcher(ch) and n1 >= 0:
                nxt.add(n1)
        return self._closure(frozenset(nxt))

    def accepts(self, states: frozenset[int]) -> bool:
        return self.accept in states

    def alive(self, states: frozenset[int]) -> bool:
        return bool(states)


def _escape_matcher(esc: str):
    if esc == "d":
        return str.isdigit
    if esc == "D":
        return lambda c: not c.isdigit()
    if esc == "w":
        return lambda c: c.isalnum() or c == "_"
    if esc == "W":
        return lambda c: not (c.isalnum() or c == "_")
    if esc == "s":
        return str.isspace
    if esc == "S":
        return lambda c: not c.isspace()
    return lambda c, want=esc: c == want


# --------------------------------------------------------------------------
# Constrained CTC prefix beam search
# --------------------------------------------------------------------------
def _log_softmax(logits: np.ndarray) -> np.ndarray:
    m = logits.max(axis=-1, keepdims=True)
    z = logits - m
    return z - np.log(np.exp(z).sum(axis=-1, keepdims=True))


def _logaddexp(a: float, b: float) -> float:
    if a <= NEG_INF:
        return b
    if b <= NEG_INF:
        return a
    hi, lo = (a, b) if a > b else (b, a)
    return hi + np.log1p(np.exp(lo - hi))


def decode(
    logits: np.ndarray,
    itos: list[str],
    *,
    pattern: str | None = None,
    charset: str | None = None,
    beam_width: int = 12,
    top_k: int = 8,
    temperature: float = 1.0,
) -> tuple[str, float]:
    """Beam-decode CTC logits, optionally constrained to a grammar/charset.

    logits: (T, C) raw scores; itos[0] must be the CTC blank.
    Returns (text, confidence) where confidence is exp(mean log-prob per
    character) — comparable to the greedy decoder's confidence.

    Falls back to the best *unconstrained* beam if the grammar admits nothing
    (a badly damaged print must still produce a reading for the operator, and
    the tool layer's own match/verify logic then fails it honestly).
    """
    logits = np.asarray(logits, dtype=np.float64)
    if temperature != 1.0:
        logits = logits / temperature
    lp = _log_softmax(logits)
    T, C = lp.shape

    nfa = RegexNFA(pattern) if pattern else None
    allowed_ids: set[int] | None = None
    if charset:
        allowed = set(charset)
        allowed_ids = {i for i, ch in enumerate(itos) if i != BLANK and ch in allowed}

    # beam: prefix -> [p_blank, p_nonblank, nfa_states]
    start_states = nfa.start() if nfa else None
    beams: dict[str, list] = {"": [0.0, NEG_INF, start_states]}

    for t in range(T):
        # only consider the most probable characters this frame (plus blank)
        order = np.argpartition(lp[t], -min(top_k + 1, C))[-(top_k + 1):]
        cands = [int(i) for i in order if i != BLANK]
        if allowed_ids is not None:
            cands = [i for i in cands if i in allowed_ids]

        nxt: dict[str, list] = {}

        def bump(prefix: str, states, pb: float = NEG_INF, pnb: float = NEG_INF) -> None:
            slot = nxt.get(prefix)
            if slot is None:
                nxt[prefix] = [pb, pnb, states]
            else:
                slot[0] = _logaddexp(slot[0], pb)
                slot[1] = _logaddexp(slot[1], pnb)

        for prefix, (pb, pnb, states) in beams.items():
            total = _logaddexp(pb, pnb)
            # 1. emit blank -> prefix unchanged
            bump(prefix, states, pb=total + lp[t, BLANK])
            # 2. repeat the last character -> prefix unchanged (CTC collapse)
            if prefix:
                last_id = _char_id(itos, prefix[-1])
                if last_id is not None:
                    bump(prefix, states, pnb=pnb + lp[t, last_id])
            # 3. extend with a new character
            for c in cands:
                ch = itos[c]
                if nfa is not None:
                    new_states = nfa.step(states, ch)
                    if not new_states:
                        continue  # grammar-illegal: never even considered
                else:
                    new_states = None
                new_prefix = prefix + ch
                if prefix and ch == prefix[-1]:
                    # same char again must be separated by a blank
                    bump(new_prefix, new_states, pnb=pb + lp[t, c])
                else:
                    bump(new_prefix, new_states, pnb=total + lp[t, c])

        if not nxt:  # grammar killed everything — decode unconstrained instead
            return decode(logits, itos, charset=charset, beam_width=beam_width,
                          top_k=top_k) if (pattern or charset) else ("", 0.0)
        beams = dict(
            sorted(nxt.items(), key=lambda kv: -_logaddexp(kv[1][0], kv[1][1]))[:beam_width]
        )

    # final: prefer beams the grammar accepts
    scored = [
        (prefix, _logaddexp(pb, pnb), states)
        for prefix, (pb, pnb, states) in beams.items()
    ]
    if nfa is not None:
        accepting = [s for s in scored if s[2] is not None and nfa.accepts(s[2])]
        if accepting:
            scored = accepting
    if not scored:
        return "", 0.0
    prefix, score, _ = max(scored, key=lambda s: s[1])
    conf = float(np.exp(score / max(len(prefix), 1)))
    if nfa is None:
        # Same padding artifact the greedy decoder strips. Only safe without a
        # grammar: a constrained read must keep satisfying the grammar it was
        # decoded under, which may itself specify surrounding spaces.
        prefix = prefix.strip()
    return prefix, min(conf, 1.0)


_ID_CACHE: dict[int, dict[str, int]] = {}


def _char_id(itos: list[str], ch: str) -> int | None:
    key = id(itos)
    table = _ID_CACHE.get(key)
    if table is None or len(table) != len(itos) - 1:
        table = {c: i for i, c in enumerate(itos) if i != BLANK}
        _ID_CACHE[key] = table
    return table.get(ch)


def pattern_for_field(spec: dict | None) -> str | None:
    """Extract a decoding grammar from a tool config.

    Uses ``pattern`` when the tool is in regex mode; otherwise derives an exact
    grammar from ``expected`` when the operator asked for an exact match — in
    verification the printed text is known, so the decoder should not be free to
    invent something else.
    """
    if not spec:
        return None
    if spec.get("match") == "regex" and spec.get("pattern"):
        return str(spec["pattern"])
    if spec.get("match") == "exact" and spec.get("expected"):
        return escape(str(spec["expected"]))
    return None


def escape(text: str) -> str:
    """Escape a literal string for use as a decoding grammar."""
    special = set(r".[]{}()*+?|\\^$")
    return "".join("\\" + c if c in special else c for c in text)
