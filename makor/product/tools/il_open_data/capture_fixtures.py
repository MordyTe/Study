"""Re-capture the offline fixtures from the LIVE data.gov.il API.

Not used by the tests. Run it once, manually, from a machine with network:

    python product/tools/il_open_data/capture_fixtures.py

It overwrites tests/fixtures/*.json with genuine responses, saves robots.txt
to tests/fixtures/robots.txt, and prints the URL + UTC date of each capture
so the README "Fixture provenance" table can be updated.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures")

CAPTURES = {
    "package_search_transport.json": core.build_url("package_search", {"q": "תחבורה", "rows": 2}),
    "package_search_empty.json": core.build_url("package_search", {"q": "zzqx_no_such_dataset_7781", "rows": 2}),
    "package_show.json": core.build_url("package_show", {"id": "mechirmnm"}),
    "datastore_search.json": core.build_url("datastore_search", {
        "resource_id": "b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", "limit": 2}),
    "datastore_search_empty.json": core.build_url("datastore_search", {
        "resource_id": "b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", "q": "zzqx_no_such_value_7781", "limit": 2}),
}


def main() -> int:
    os.makedirs(FIXTURES, exist_ok=True)
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    for name, url in CAPTURES.items():
        data = core.fetch_json(url)
        with open(os.path.join(FIXTURES, name), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print(f"{today}  {name}  <-  {url}")
    req = urllib.request.Request("https://data.gov.il/robots.txt",
                                 headers={"User-Agent": core.USER_AGENT})
    with urllib.request.urlopen(req, timeout=core.TIMEOUT_SECONDS) as resp:
        robots = resp.read().decode("utf-8", "replace")
    with open(os.path.join(FIXTURES, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(robots)
    print(f"{today}  robots.txt  <-  https://data.gov.il/robots.txt\n{robots}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
