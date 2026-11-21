#!/usr/bin/env python3
"""
Build beach -> state legislator lookup for Shoreline Ledger.

Inputs (all offline once fetched; no API key anywhere):
  1. Site list: <script type="application/json" id="data"> in shoreline-ledger/index.html
  2. District boundaries: Census cartographic boundary files (public domain), either
       cb_2025_us_sldu_500k.zip + cb_2025_us_sldl_500k.zip   (national, ~11 MB + ~16 MB)
     or per-state cb_YYYY_SS_sld[ul]_500k.zip files, placed in --boundaries DIR.
     Any vintage/scale with STATEFP + GEOID (+ NAMELSAD) fields works.
  3. Legislators: github.com/openstates/people (CC0), cloned with git (allowed here).
  4. Census GEOID -> OCD division mapping: vendored configs from
     github.com/openstates/openstates-geo (vendor/openstates-geo-jurisdictions),
     district display names from the `openstates` PyPI package metadata.

Usage:
  python3 build_legislators.py --boundaries ./boundaries          # full build
  python3 build_legislators.py --selftest                          # no boundaries needed:
        checks GEOID->OCD->name->legislator chain for every district of the site states
Deps: pip install shapely pyshp pyyaml openstates
"""
import argparse, collections, datetime, glob, json, math, os, re, subprocess, sys, zipfile
from urllib.parse import urlparse

import yaml
import shapefile  # pyshp
from shapely.geometry import shape, Point
from shapely.ops import nearest_points
from shapely.strtree import STRtree
import openstates.metadata as osmeta

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_INDEX = "/home/claude/shoreline-ledger/index.html"
DEF_PEOPLE = os.path.join(HERE, "cache", "people")
VENDOR = os.path.join(HERE, "vendor", "openstates-geo-jurisdictions")

STATE_ABBR = {"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO",
 "Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL",
 "Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD",
 "Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT",
 "Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY",
 "North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA",
 "Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT",
 "Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY",
 "Puerto Rico":"PR","District of Columbia":"DC"}


def load_sites(index_path):
    h = open(index_path, encoding="utf-8").read()
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', h, re.S)
    return json.loads(m.group(1))["sites"]


def git_head(path):
    try:
        return subprocess.check_output(["git", "-C", path, "log", "-1", "--format=%h %cs"], text=True).strip()
    except Exception:
        return "unknown"


def ensure_people(path, update):
    if not os.path.isdir(os.path.join(path, "data")):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.check_call(["git", "clone", "-q", "--depth", "1", "https://github.com/openstates/people", path])
    elif update:
        subprocess.call(["git", "-C", path, "pull", "-q", "--depth", "1"])


# ---------------- GEOID -> OCD division ----------------
class Mapper:
    """Re-implements openstates-geo utils/geojson.py::_merge_ids for one feature."""
    def __init__(self, vendor_dir):
        self.cfg = {}
        for f in glob.glob(os.path.join(vendor_dir, "*.yml")):
            c = yaml.safe_load(open(f))
            st = osmeta.lookup(name=c["name"]) if c.get("name") else None
            if st:
                self.cfg[st.abbr.upper()] = c
        self.names = {}  # ocd id -> (chamber, district name)
        self.by_norm = collections.defaultdict(dict)  # abbr -> {(chamber, norm name): ocd}
        for abbr in self.cfg:
            st = osmeta.lookup(abbr=abbr.lower())
            for chamber in ("upper", "lower", "legislature"):
                ch = getattr(st, chamber, None)
                if not ch:
                    continue
                for d in ch.districts:
                    self.names[d.division_id] = (chamber, d.name)
                    self.by_norm[abbr][(chamber, norm(d.name))] = d.division_id

    def ocd(self, abbr, dt, geoid, namelsad=None):
        c = self.cfg.get(abbr)
        if not c or not geoid or geoid.endswith("ZZ"):
            return None
        maps = c["id-mappings"]
        district_type = maps.get(dt, {}).get("sld-prefix", dt)
        census_id = f"{district_type}-{geoid}"
        for cm in maps.get("custom", []) or []:
            if cm.get("sld-id") == census_id:
                return cm["os-id"]
        rx = maps.get(district_type, {}).get("sld-match")
        if rx:
            m = re.search(rx, census_id)
            if m:
                return f"{c['os-id-prefix']}/{district_type}:{m.group(1).lstrip('0')}".lower()
        # fallback: match Census district name against Open States district names
        if namelsad:
            chamber = {"sldu": "upper", "sldl": "lower"}[dt]
            if abbr == "NE":
                chamber = "legislature"
            n = norm(re.sub(r"(State (Senate|House|Legislative|Assembly)|District|Senate|House|Assembly)", " ", namelsad))
            return self.by_norm[abbr].get((chamber, n))
        return None


def norm(s):
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"^0+(\d)", r"\1", s)


# ---------------- legislators ----------------
def load_people(people_dir, abbrs, today):
    out = collections.defaultdict(list)  # (abbr, chamber, district) -> [person]
    for abbr in abbrs:
        st = osmeta.lookup(abbr=abbr.lower())
        official = urlparse(st.url).hostname or "" if st.url else ""
        off_root = ".".join(official.split(".")[-2:]) if official else ""
        for f in glob.glob(os.path.join(people_dir, "data", abbr.lower(), "legislature", "*.yml")):
            p = yaml.safe_load(open(f, encoding="utf-8"))
            for r in p.get("roles", []):
                if r.get("type") not in ("upper", "lower", "legislature"):
                    continue
                sd, ed = r.get("start_date"), r.get("end_date")
                if (sd and str(sd) > today) or (ed and str(ed) < today):
                    continue
                out[(abbr, r["type"], r["district"])].append(person_record(p, r, off_root))
    return out


def person_record(p, r, off_root):
    links = [l["url"] for l in p.get("links", []) if l.get("url")]
    def score(u):
        h = urlparse(u).hostname or ""
        if off_root and h.endswith(off_root): return 0
        if h.endswith(".gov") or ".state." in h or h.endswith(".us"): return 1
        return 2
    url = sorted(links, key=score)[0] if links else None
    email = p.get("email") or next((o["email"] for o in p.get("offices", []) if o.get("email")), None)
    return {"name": p["name"], "district": r["district"], "url": url, "email": email,
            "openstates_id": p["id"]}


# ---------------- boundaries ----------------
def load_boundaries(bdir, want_fips):
    feats = collections.defaultdict(list)  # (fips, dt) -> [(geom, props)]
    srcs = sorted(glob.glob(os.path.join(bdir, "*.zip")) + glob.glob(os.path.join(bdir, "*.shp")))
    used = []
    for src in srcs:
        base = os.path.basename(src).lower()
        dt = "sldu" if "sldu" in base else "sldl" if "sldl" in base else None
        if not dt:
            continue
        used.append(os.path.basename(src))
        r = shapefile.Reader(src)
        fields = [f[0] for f in r.fields[1:]]
        for sr in r.iterShapeRecords():
            props = dict(zip(fields, sr.record))
            fips = props.get("STATEFP") or props.get("STATEFP20")
            if fips not in want_fips:
                continue
            g = shape(sr.shape.__geo_interface__)
            if not g.is_valid:
                g = g.buffer(0)
            feats[(fips, dt)].append((g, props))
    return feats, used


def haversine_km(a, b):
    (lon1, lat1), (lon2, lat2) = a, b
    p = math.pi / 180
    h = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def locate(pt, items, tree):
    for i in tree.query(pt, predicate="intersects"):
        return items[i], 0.0, "inside"
    i = tree.nearest(pt)
    g, _ = items[i]
    q = nearest_points(pt, g)[1]
    return items[i], haversine_km((pt.x, pt.y), (q.x, q.y)), "nearest"


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=DEF_INDEX)
    ap.add_argument("--boundaries", default=os.path.join(HERE, "boundaries"))
    ap.add_argument("--people", default=DEF_PEOPLE)
    ap.add_argument("--update-people", action="store_true")
    ap.add_argument("--max-km", type=float, default=5.0)
    ap.add_argument("--out", default=os.path.join(HERE, "beach_legislators.json"))
    ap.add_argument("--report", default=os.path.join(HERE, "beach_legislators_report.txt"))
    ap.add_argument("--today", default=datetime.date.today().isoformat())
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    sites = load_sites(a.index)
    abbrs = sorted({STATE_ABBR[s["state"]] for s in sites})
    ensure_people(a.people, a.update_people)
    mapper = Mapper(VENDOR)
    people = load_people(a.people, abbrs, a.today)

    if a.selftest:
        return selftest(abbrs, mapper, people)

    fips_of = {osmeta.lookup(abbr=x.lower()).fips: x for x in abbrs}
    feats, used = load_boundaries(a.boundaries, set(fips_of))
    if not used:
        sys.exit(f"No cb_*_sldu/sldl zip or shp found in {a.boundaries}")
    trees = {k: STRtree([g for g, _ in v]) for k, v in feats.items()}

    result, log = {}, []
    stats = collections.Counter()
    fail_by_state = collections.defaultdict(collections.Counter)
    for s in sites:
        abbr = STATE_ABBR[s["state"]]
        fips = osmeta.lookup(abbr=abbr.lower()).fips
        pt = Point(s["lon"], s["lat"])
        rec = {"state": abbr, "upper": [], "lower": [], "as_of": a.today}
        ok = True
        chambers = [("sldu", "upper")] if abbr == "NE" else [("sldu", "upper"), ("sldl", "lower")]
        for dt, key in chambers:
            if (fips, dt) not in trees:
                ok = False; fail_by_state[abbr][f"{dt}:no boundary file"] += 1; continue
            (g, props), km, how = locate(pt, feats[(fips, dt)], trees[(fips, dt)])
            geoid = props.get("GEOID") or props.get("GEOID20")
            nm = props.get("NAMELSAD") or props.get("NAMELSAD20") or props.get("NAME")
            if how == "nearest":
                rec.setdefault("match", {})[key] = f"nearest {km:.2f} km"
                if km > a.max_km:
                    ok = False; fail_by_state[abbr][f"{dt}:offshore>{a.max_km}km"] += 1
                    rec.setdefault("unresolved", {})[key] = f"nearest district {nm} is {km:.1f} km away"
                    continue
            ocd = mapper.ocd(abbr, dt, geoid, nm)
            if not ocd or ocd not in mapper.names:
                ok = False; fail_by_state[abbr][f"{dt}:GEOID {geoid} ({nm}) unmapped"] += 1; continue
            chamber, dname = mapper.names[ocd]
            reps = people.get((abbr, chamber, dname), [])
            if not reps:
                ok = False; fail_by_state[abbr][f"{dt}:no current member for {dname}"] += 1
            rec[key] = reps
            rec.setdefault("districts", {})[key] = dname
        if abbr == "NE":
            rec["note"] = "Nebraska Legislature is unicameral; members listed under 'upper'."
        stats["resolved" if ok else "partial"] += 1
        result[str(s["id"])] = rec

    meta = {"_meta": {"built": a.today, "boundaries": used,
                      "openstates_people": git_head(a.people),
                      "mapping": open(os.path.join(HERE, "vendor", "SOURCE.txt")).read().strip(),
                      "max_offshore_km": a.max_km}}
    json.dump({**meta, **result}, open(a.out, "w"), ensure_ascii=False, indent=0)
    with open(a.report, "w") as f:
        f.write(f"sites {len(sites)}  fully resolved {stats['resolved']}  partial/failed {stats['partial']}\n")
        f.write(json.dumps(meta["_meta"]) + "\n")
        for st in sorted(fail_by_state):
            f.write(f"{st}: " + "; ".join(f"{k} x{v}" for k, v in fail_by_state[st].most_common()) + "\n")
    print(open(a.report).read())


def selftest(abbrs, mapper, people):
    """Without boundary files: for every Open States district of each site state, synthesize
    the Census GEOID it should have, run it through the mapper, and check a current member exists."""
    print(f"people entries: {sum(len(v) for v in people.values())}")
    bad = 0
    for abbr in abbrs:
        st = osmeta.lookup(abbr=abbr.lower())
        c = mapper.cfg[abbr]
        rev = {cm["os-id"]: cm["sld-id"] for cm in (c["id-mappings"].get("custom") or []) if "sld-id" in cm}
        probs = collections.Counter(); n = 0
        for chamber, dt in (("upper", "sldu"), ("lower", "sldl"), ("legislature", "sldu")):
            ch = getattr(st, chamber, None)
            if not ch:
                continue
            for d in ch.districts:
                n += 1
                if d.division_id in rev:
                    geoid = rev[d.division_id].split("-", 1)[1]
                else:
                    tail = d.division_id.rsplit(":", 1)[1].upper()
                    geoid = st.fips + (tail.zfill(3) if tail.isdigit() else
                                       re.sub(r"^(\d+)", lambda m: m.group(1).zfill(3 if len(tail) <= 3 else 2), tail))
                    if abbr == "AK" and chamber == "upper":
                        geoid = st.fips + "00" + tail
                got = mapper.ocd(abbr, dt, geoid)
                if got != d.division_id:
                    probs[f"{chamber}:map"] += 1
                if not people.get((abbr, chamber, d.name)):
                    probs[f"{chamber}:no current member ({d.name})" if len(probs) < 6 else f"{chamber}:vacant"] += 1
        bad += sum(probs.values())
        print(f"{abbr}: {n} districts", dict(probs) if probs else "OK")
    print("selftest problems:", bad)


if __name__ == "__main__":
    main()
