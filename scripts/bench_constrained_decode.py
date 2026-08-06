"""Measure greedy vs beam vs grammar-constrained decoding on the REAL golden set."""
import sys, time
from pathlib import Path
import numpy as np
import cv2

sys.path.insert(0, "/Users/shashikant/Personal/camera/vision/src")
from vis.tools.vis_ocr_reader import VisOcrReader, _find_model, _preprocess
from vis.tools.constrained_decode import decode

ROOT = Path("/Users/shashikant/Personal/camera/ocr-trainer/.claude/worktrees/adoring-jemison-51068e/data/blister_golden")

# The per-field grammars an operator defines when teaching the recipe
GRAMMARS = [
    (r"B\.No\.", r"B\.No\.[A-Z0-9]{5,12}"),
    (r"MFG",     r"MFG\. \d{2}/\d{4}"),
    (r"EXP",     r"EXP\. \d{2}/\d{4}"),
    (r"M\.R\.P", r"M\.R\.P Rs\. \d{3}\.\d{2}"),
    (r"Per ",    r"Per [A-Z]{2} Tablets"),
    (r"\(INCL",  r"\(INCL\. OF ALL TAXES\)"),
]
import re
def grammar_for(truth):
    for probe, pat in GRAMMARS:
        if re.match(probe, truth):
            return pat
    return None

def cer(a, b):
    """char error distance / len(truth)"""
    if not b: return 1.0
    d = np.zeros((len(a)+1, len(b)+1), int)
    d[:,0] = np.arange(len(a)+1); d[0,:] = np.arange(len(b)+1)
    for i in range(1, len(a)+1):
        for j in range(1, len(b)+1):
            d[i,j] = min(d[i-1,j]+1, d[i,j-1]+1, d[i-1,j-1] + (a[i-1]!=b[j-1]))
    return d[len(a), len(b)] / len(b)

reader = VisOcrReader(_find_model())
reader._ensure()
items = [l.split("\t") for l in (ROOT/"labels.txt").read_text().strip().split("\n")]
print(f"golden set: {len(items)} real crops, model {reader.model_path.name}\n")

res = {k: {"field":0, "cer":[], "ms":[]} for k in ("greedy","beam","constrained")}
per_field = {}
for rel, truth in items:
    img = cv2.imread(str(ROOT/rel), cv2.IMREAD_GRAYSCALE)
    if img is None: continue
    x = _preprocess(img, reader._img_w)
    logits = np.asarray(reader._sess.run(None, {reader._input: x})[0])[:,0,:]
    pat = grammar_for(truth)

    runs = {}
    t0=time.perf_counter(); runs["greedy"] = reader._decode(logits)[0]; g_ms=(time.perf_counter()-t0)*1000
    t0=time.perf_counter(); runs["beam"] = decode(logits, reader._itos)[0]; b_ms=(time.perf_counter()-t0)*1000
    t0=time.perf_counter(); runs["constrained"] = decode(logits, reader._itos, pattern=pat)[0] if pat else runs["beam"]; c_ms=(time.perf_counter()-t0)*1000

    for k, ms in (("greedy",g_ms),("beam",b_ms),("constrained",c_ms)):
        res[k]["field"] += (runs[k] == truth)
        res[k]["cer"].append(cer(runs[k], truth))
        res[k]["ms"].append(ms)
    key = truth.split()[0][:8]
    pf = per_field.setdefault(key, {"n":0,"greedy":0,"constrained":0})
    pf["n"] += 1; pf["greedy"] += runs["greedy"]==truth; pf["constrained"] += runs["constrained"]==truth

n = len(res["greedy"]["cer"])
print(f"{'mode':<14}{'field acc':>11}{'char acc':>11}{'ms/field':>11}")
print("-"*47)
for k in ("greedy","beam","constrained"):
    r = res[k]
    print(f"{k:<14}{r['field']/n*100:>10.1f}%{(1-np.mean(r['cer']))*100:>10.1f}%{np.mean(r['ms']):>10.1f}")

print(f"\n{'field type':<12}{'n':>4}{'greedy':>9}{'constrained':>13}")
print("-"*38)
for k, v in sorted(per_field.items()):
    print(f"{k:<12}{v['n']:>4}{v['greedy']/v['n']*100:>8.0f}%{v['constrained']/v['n']*100:>12.0f}%")
