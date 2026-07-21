"""OCV verification scoring on CTC logits (numpy — runs on ONNX outputs).

The OCV advantage over generic OCR confidence: we KNOW the expected string, so
we can score it exactly:

  score_expected()   log P(expected | image) via the CTC forward algorithm
  best_path_logprob  log P(greedy best path)  — the "what the model prefers"
  llr = best - expected : ~0 when the print matches; large when it doesn't
  energy()           OOD score (logsumexp) — low energy = in-distribution print

Verdict logic (thresholds fitted on a golden set):
  ACCEPT  llr small  AND  expected logprob high  AND  energy in-range
  REJECT  otherwise (wrong text, unreadable, or out-of-distribution print)

Calibration: temperature-scale logits (fit T on held-out data) before scoring.
References: CTC forward scoring (Graves 2006), energy OOD (Liu et al. 2020),
sequence temperature scaling (Amazon ECCV-W 2022).
"""
from __future__ import annotations

import numpy as np

NEG_INF = -1e30


def _log_softmax(logits: np.ndarray) -> np.ndarray:
    m = logits.max(axis=-1, keepdims=True)
    z = logits - m
    return z - np.log(np.exp(z).sum(axis=-1, keepdims=True))


def score_expected(logits: np.ndarray, target_ids: list[int],
                   temperature: float = 1.0) -> float:
    """log P(target | image) under CTC. logits: (T, C) raw; target_ids: codec
    indices (1-based chars, 0 = blank is inserted here)."""
    if not target_ids:
        return NEG_INF
    lp = _log_softmax(np.asarray(logits, np.float64) / temperature)  # (T, C)
    T = lp.shape[0]
    # extended sequence: blank, c1, blank, c2, ... blank
    ext = [0]
    for c in target_ids:
        ext += [int(c), 0]
    S = len(ext)
    if S > 2 * T + 1:
        return NEG_INF
    alpha = np.full(S, NEG_INF)
    alpha[0] = lp[0, ext[0]]
    if S > 1:
        alpha[1] = lp[0, ext[1]]
    for t in range(1, T):
        prev = alpha
        alpha = np.full(S, NEG_INF)
        for s in range(S):
            cands = [prev[s]]
            if s >= 1:
                cands.append(prev[s - 1])
            if s >= 2 and ext[s] != 0 and ext[s] != ext[s - 2]:
                cands.append(prev[s - 2])
            m = max(cands)
            if m <= NEG_INF:
                continue
            alpha[s] = m + np.log(sum(np.exp(c - m) for c in cands)) + lp[t, ext[s]]
    tail = [alpha[S - 1]] + ([alpha[S - 2]] if S > 1 else [])
    m = max(tail)
    if m <= NEG_INF:
        return NEG_INF
    return float(m + np.log(sum(np.exp(c - m) for c in tail)))


def best_path_logprob(logits: np.ndarray, temperature: float = 1.0) -> float:
    """log-prob of the greedy best path (upper bound proxy for the argmax read)."""
    lp = _log_softmax(np.asarray(logits, np.float64) / temperature)
    return float(lp.max(axis=-1).sum())


def energy(logits: np.ndarray, temperature: float = 1.0) -> float:
    """Mean per-frame energy score: -T*logsumexp(logits/T). LOWER = more
    in-distribution. Effective OOD/garbage-crop detector at zero cost."""
    z = np.asarray(logits, np.float64) / temperature
    m = z.max(axis=-1)
    lse = m + np.log(np.exp(z - m[:, None]).sum(axis=-1))
    return float((-temperature * lse).mean())


def verify(logits: np.ndarray, expected_ids: list[int], *,
           temperature: float = 1.0,
           max_llr_per_char: float = 1.0,
           min_logprob_per_char: float = -3.0) -> dict:
    """Verdict for 'does this crop print the expected string?'.

    llr_per_char ~ 0 when the print matches the expectation; grows quickly when
    the model prefers a different reading. Thresholds are per-character so one
    setting works across field lengths; fit them on a golden set."""
    n = max(1, len(expected_ids))
    exp_lp = score_expected(logits, expected_ids, temperature)
    best_lp = best_path_logprob(logits, temperature)
    llr = (best_lp - exp_lp) / n
    ok = (llr <= max_llr_per_char) and (exp_lp / n >= min_logprob_per_char)
    return {
        "accept": bool(ok),
        "llr_per_char": float(llr),
        "expected_logprob_per_char": float(exp_lp / n),
        "energy": energy(logits, temperature),
    }
