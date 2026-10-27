# Fixtures

Offline CKAN action-API responses used by the tests. The shape follows CKAN 2.x
(`{"help", "success", "result"}`); `broken.json` is a deliberately truncated
body for the bad-JSON test. See the tool README ("Fixture provenance") for
whether each file is a live capture or a schema-shaped sample, and run
`python product/tools/il_open_data/capture_fixtures.py` to replace them with
live captures.
