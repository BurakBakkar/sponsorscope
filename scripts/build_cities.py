"""Build sponsorscope/geo/data/cities.tsv from GeoNames cities15000 (CC BY 4.0).

Run once, then commit the output:  uv run python scripts/build_cities.py
For duplicate names the most populous city wins (London → GB, not London, Ontario).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx

URL = "https://download.geonames.org/export/dump/cities15000.zip"
OUT = Path(__file__).resolve().parent.parent / "sponsorscope" / "geo" / "data" / "cities.tsv"


def main() -> None:
    data = httpx.get(URL, timeout=120, follow_redirects=True).raise_for_status().content
    best: dict[str, tuple[str, int]] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf, zf.open("cities15000.txt") as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8"):
            cols = line.rstrip("\n").split("\t")
            name, ascii_name, cc, pop = cols[1], cols[2], cols[8], int(cols[14] or 0)
            for key in {name.lower().strip(), ascii_name.lower().strip()}:
                if key and (key not in best or pop > best[key][1]):
                    best[key] = (cc, pop)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        for key in sorted(best):
            f.write(f"{key}\t{best[key][0]}\n")
    print(f"wrote {len(best)} cities to {OUT}")


if __name__ == "__main__":
    main()
