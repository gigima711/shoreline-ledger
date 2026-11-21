"""Pack the Yale Bright Star Catalogue (5th rev., Hoffleit & Warren 1991) into a small binary for the globe's sky.
Source: bsc5-short.json from github.com/brettonw/YaleBrightStarCatalog (a JSON conversion of the BSC5 ASCII file).
Output assets/sky/bsc5.bin, sorted brightest first, 6 bytes per star (little-endian):
  uint16 RA  (J2000, 0..65535 = 0..24 h)
  int16  Dec (J2000, -32767..32767 = -90..+90 deg)
  uint8  V   (visual magnitude, (V + 1.5) * 30)
  uint8  K   (colour temperature, K / 200)
Usage: python3 scripts/build_stars.py bsc5-short.json assets/sky/bsc5.bin [max_mag]"""
import json, re, struct, sys
src, out = sys.argv[1], sys.argv[2]; maxv = float(sys.argv[3]) if len(sys.argv) > 3 else 5.5
def ra(s):
    h, m, x = map(float, re.findall(r'[\d.]+', s)); return (h + m / 60 + x / 3600) / 24
def dec(s):
    d, m, x = map(float, re.findall(r'[\d.]+', s)); v = d + m / 60 + x / 3600; return -v if s.strip()[0] in '-−' else v
rows = []
for r in json.load(open(src)):
    try: v = float(r['V'])
    except (KeyError, ValueError): continue
    if v > maxv or 'RA' not in r: continue
    rows.append((v, ra(r['RA']), dec(r['Dec']), float(r.get('K') or 6000)))
rows.sort()
with open(out, 'wb') as f:
    for v, a, d, k in rows:
        f.write(struct.pack('<Hhbb'.replace('b', 'B'), min(65535, round(a * 65535)), round(d / 90 * 32767), min(255, round((v + 1.5) * 30)), min(255, round(k / 200))))
print(len(rows), 'stars; <=4.5:', sum(r[0] <= 4.5 for r in rows), '<=5.0:', sum(r[0] <= 5.0 for r in rows))
