"""Build assets/intro/drifters.png for the opening animation.

Input: drifters.json = {ID: [[day, lat, lon], ...]} pulled from NOAA GDP ERDDAP
(drifter_6hour_qc, 2019-2024, one point every 4 days). Data: NOAA Global Drifter
Program (AOML), CC BY 4.0, doi:10.25921/7ntx-z961.
Tracks are split at gaps, retimed to a common start (as NASA SVS did in its
"Garbage Patch Visualization Experiment"), resampled every STEP days, and packed
as unit-sphere xyz in RGB (one row per track) plus a JSON of row lengths.
"""
import json, math, sys, random
import numpy as np
from PIL import Image
STEP, KEYS, N = 8, 64, 1600
src, out = sys.argv[1], sys.argv[2]
T = json.load(open(src))
segs = []
for k, pts in T.items():
    pts.sort()
    cur = [pts[0]]
    for p in pts[1:]:
        if p[0] - cur[-1][0] > 20 or abs(p[2] - cur[-1][2]) > 30 and abs(abs(p[2] - cur[-1][2]) - 360) > 30:
            if len(cur) > 1: segs.append(cur)
            cur = [p]
        else: cur.append(p)
    segs.append(cur)
segs = [s for s in segs if s[-1][0] - s[0][0] >= 120]
def xyz(lat, lon):
    phi, th = math.radians(90 - lat), math.radians(lon + 180)
    return (-math.sin(phi) * math.cos(th), math.cos(phi), math.sin(phi) * math.sin(th))
random.seed(7)
# spread picks over the globe: bucket by start cell, round-robin
buckets = {}
for s in segs: buckets.setdefault((int(s[0][1] // 10), int(s[0][2] // 15)), []).append(s)
for b in buckets.values(): b.sort(key=lambda s: -(s[-1][0] - s[0][0]))
pick, i = [], 0
while len(pick) < N and any(buckets.values()):
    for key in list(buckets):
        if buckets[key]: pick.append(buckets[key].pop(0))
        if len(pick) >= N: break
img = np.zeros((len(pick), KEYS, 3), np.uint8); lens = []
for r, s in enumerate(pick):
    d0 = s[0][0]; days = np.array([p[0] - d0 for p in s], float)
    v = np.array([xyz(p[1], p[2]) for p in s])
    n = min(KEYS, int(days[-1] // STEP) + 1); lens.append(n)
    for k in range(KEYS):
        t = min(k, n - 1) * STEP
        j = np.searchsorted(days, t); j = min(max(j, 1), len(days) - 1)
        a = (t - days[j - 1]) / max(1e-6, days[j] - days[j - 1]); a = min(max(a, 0), 1)
        p = v[j - 1] * (1 - a) + v[j] * a; p /= np.linalg.norm(p)
        img[r, k] = np.round((p * 0.5 + 0.5) * 255)
Image.fromarray(img, 'RGB').save(out + '.png', optimize=True)
json.dump({'keys': KEYS, 'stepDays': STEP, 'len': lens, 'n': len(pick), 'src': 'NOAA Global Drifter Program (AOML), 2019-2024, CC BY 4.0'}, open(out + '.json', 'w'), separators=(',', ':'))
print(len(segs), 'segments;', len(pick), 'picked; median length', int(np.median(lens)) * STEP, 'days')
