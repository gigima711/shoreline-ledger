# Shoreline Ledger

An interactive look at U.S. beach litter, built for **Arbiter Hacks** (theme: *Rethinking Waste*).

**Live site:** https://gigima711.github.io/shoreline-ledger/

- **Globe**: 847 beaches surveyed by NOAA's Marine Debris Monitoring and Assessment Project (MDMAP), with live day and night.
- **Walk a beach**: each beach is rebuilt in 3D from its own survey data. Walk the shore, learn what each item is, and sort it into the right bin. Shown in daylight by default; the real sky at that beach is one click away.
- **Evidence**: across 8,119 NOAA surveys, beaches in states without a bottle deposit carry about 2.5× the share of drink containers found in deposit states (95% range 1.8–3.5×; 1.95× without Hawaii). Comparing states on the same coast, the gap holds on the Pacific (2.69×, 1.9–3.9×) but not from Maine to Virginia (1.08×). The page shows the method and its limits.
- **Act**: a letter to your state legislator, pre-filled with your beach's own numbers.

## Run it
Open `index.html` through any static web server (for example `python3 -m http.server`), or visit the GitHub Pages site. Everything it needs (three.js, D3, TopoJSON, fonts) is in `assets/lib`, so it works without outside CDNs.

URL options: `?demo=1` hands-off tour for recording; `?t=2026-11-20T18:00Z` pretend it is another time; `?debug` exposes test hooks (`window.__enter`, `__fly`, `__bake`, …).

## Method notes
- Share of drink containers = plastic drink bottles, cans and glass bottles over all items counted, pooled across surveys. 95% ranges come from re-sampling beaches (bootstrap).
- Same-coast comparison: Pacific (CA, OR vs WA, AK), Atlantic Maine–Virginia (ME, MA, CT, NY vs NH, RI, NJ, DE, MD, VA), Great Lakes (MI and New York's lake shores vs OH, IL, IN, WI); 4,000 beach re-samples within each coast.
- County names are matched from each beach's coordinates to U.S. Census county boundaries (us-atlas).

## Data and credits
Survey data: NOAA MDMAP (mdmap.orr.noaa.gov). Beach photos come from Wikimedia Commons and Flickr under CC0, public domain, CC BY or CC BY-SA, credited on each photo card. 3D models, textures, libraries, fonts and other sources are listed in `credits.html`.

## License
Code: MIT. Third-party photos, models, textures, libraries and fonts keep their own licenses (see `credits.html`; font licenses in `assets/lib/fonts`).
