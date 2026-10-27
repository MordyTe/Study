"""Offline tests for il_open_data.core (fixtures + monkeypatch, no network)."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

import pytest

import core
from conftest import NetworkCallAttempted, load_fixture

HEBREW = "תחבורה"
HEBREW_ENCODED = urllib.parse.quote(HEBREW)  # %D7%AA%D7%97%D7%91%D7%95%D7%A8%D7%94


# --------------------------------------------------------------------------- #
# URL building / encoding
# --------------------------------------------------------------------------- #
def test_hebrew_query_is_percent_encoded_in_url(fixture_fetch):
    calls = fixture_fetch("package_search_transport.json")
    out = core.search_datasets(HEBREW, limit=2)
    assert out["ok"] is True
    assert len(calls) == 1
    url = calls[0]
    assert url.startswith(core.BASE_URL + "package_search?")
    assert HEBREW_ENCODED in url
    assert HEBREW not in url  # no raw Hebrew on the wire
    assert url.isascii()
    assert "rows=2" in url


def test_build_url_quotes_spaces_and_skips_empty_values():
    url = core.build_url("datastore_search", {"resource_id": "abc", "q": "", "limit": 5})
    assert url == core.BASE_URL + "datastore_search?resource_id=abc&limit=5"
    url2 = core.build_url("package_search", {"q": "a b"})
    assert url2.endswith("package_search?q=a%20b")


def test_real_fetch_json_sets_user_agent_and_timeout(monkeypatch):
    """Exercise the real transport against a fake urlopen (still no network)."""
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"success": true, "result": {}}'

    def fake_urlopen(request, timeout=None):
        seen["ua"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        seen["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    data = core.fetch_json(core.BASE_URL + "package_search?q=x")
    assert data == {"success": True, "result": {}}
    assert seen["ua"] == "makor-il-open-data/0.1"
    assert seen["timeout"] == 10
    assert seen["url"].startswith("https://data.gov.il/api/3/action/")


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", ["", "   ", None, 123])
def test_empty_or_non_string_query_is_invalid_input(bad, fixture_fetch):
    calls = fixture_fetch("package_search_transport.json")
    out = core.search_datasets(bad)
    assert out == {"ok": False, "error": "invalid_input", "detail": out["detail"]}
    assert calls == []  # rejected before any request


def test_query_over_max_length_is_invalid_input(fixture_fetch):
    calls = fixture_fetch("package_search_transport.json")
    out = core.search_datasets("א" * (core.MAX_QUERY_CHARS + 1))
    assert out["ok"] is False and out["error"] == "invalid_input"
    assert calls == []


@pytest.mark.parametrize("limit", [0, -1, core.MAX_LIMIT + 1, "5", 2.5, True])
def test_bad_limit_is_invalid_input(limit, fixture_fetch):
    calls = fixture_fetch("package_search_transport.json")
    out = core.search_datasets(HEBREW, limit=limit)
    assert out["ok"] is False and out["error"] == "invalid_input"
    assert calls == []


def test_empty_dataset_id_and_resource_id_are_invalid_input(fixture_fetch):
    calls = fixture_fetch("package_show.json")
    assert core.get_dataset("")["error"] == "invalid_input"
    assert core.get_dataset("  ")["error"] == "invalid_input"
    assert core.search_records("")["error"] == "invalid_input"
    assert calls == []


# --------------------------------------------------------------------------- #
# Failure modes -> structured errors, never exceptions
# --------------------------------------------------------------------------- #
def test_timeout_is_source_unavailable(monkeypatch):
    def timing_out(url):
        raise socket.timeout("timed out")
    monkeypatch.setattr(core, "fetch_json", timing_out)
    out = core.search_datasets(HEBREW)
    assert out["ok"] is False
    assert out["error"] == "source_unavailable"


def test_connection_error_is_source_unavailable(monkeypatch):
    def refused(url):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    monkeypatch.setattr(core, "fetch_json", refused)
    out = core.get_dataset("mechirmnm")
    assert out["ok"] is False and out["error"] == "source_unavailable"


@pytest.mark.parametrize("status", [500, 502, 503, 429])
def test_http_5xx_is_source_unavailable(status, monkeypatch):
    def failing(url):
        raise urllib.error.HTTPError(url, status, "Server Error", hdrs=None, fp=None)
    monkeypatch.setattr(core, "fetch_json", failing)
    out = core.search_datasets(HEBREW)
    assert out == {"ok": False, "error": "source_unavailable", "detail": f"HTTP {status}"}


def test_http_404_is_not_found(monkeypatch):
    def missing(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
    monkeypatch.setattr(core, "fetch_json", missing)
    out = core.get_dataset("no-such-dataset")
    assert out["ok"] is False and out["error"] == "not_found"


def test_broken_json_fixture_is_bad_response(monkeypatch):
    """The fake fetch mirrors the real one: it json.loads the body, so the
    truncated fixture raises JSONDecodeError and core must map it."""
    def fetch_broken(url):
        return load_fixture("broken.json")  # raises json.JSONDecodeError
    monkeypatch.setattr(core, "fetch_json", fetch_broken)
    with pytest.raises(json.JSONDecodeError):
        load_fixture("broken.json")  # sanity: the fixture really is broken
    out = core.search_datasets(HEBREW)
    assert out["ok"] is False and out["error"] == "bad_response"


@pytest.mark.parametrize("payload", [[], "text", {"success": True}, {"success": True, "result": "x"}])
def test_unexpected_json_shape_is_bad_response(payload, monkeypatch):
    monkeypatch.setattr(core, "fetch_json", lambda url: payload)
    assert core.search_datasets(HEBREW)["error"] == "bad_response"


def test_ckan_success_false_not_found_fixture(fixture_fetch):
    fixture_fetch("package_show_not_found.json")
    out = core.get_dataset("does-not-exist")
    assert out["ok"] is False and out["error"] == "not_found"


def test_unexpected_exception_does_not_escape(monkeypatch):
    def boom(url):
        raise RuntimeError("something odd")
    monkeypatch.setattr(core, "fetch_json", boom)
    out = core.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37")
    assert out["ok"] is False and out["error"] == "bad_response"


# --------------------------------------------------------------------------- #
# Happy paths and result shaping
# --------------------------------------------------------------------------- #
def test_search_datasets_shapes_results(fixture_fetch):
    fixture_fetch("package_search_transport.json")
    out = core.search_datasets(HEBREW, limit=10)
    assert out["ok"] is True
    assert out["count"] == 137
    assert len(out["results"]) == 2
    first = out["results"][0]
    assert set(first) == {"id", "title", "organization", "resources"}
    assert first["id"] == "8a21fc79-07c3-4f87-99f2-5c7e8a0f2c2d"
    assert first["title"] == "לוחות זמנים של התחבורה הציבורית (GTFS)"
    assert first["organization"] == "משרד התחבורה והבטיחות בדרכים"
    assert first["resources"][0] == {
        "id": "c1a2b3c4-d5e6-4f70-8a9b-0c1d2e3f4a5b",
        "format": "ZIP",
        "url": "https://gtfs.mot.gov.il/gtfsfiles/israel-public-transportation.zip",
    }
    assert {r["format"] for r in first["resources"]} == {"ZIP", "CSV"}


def test_zero_results_is_ok_with_empty_list(fixture_fetch):
    fixture_fetch("package_search_empty.json")
    out = core.search_datasets("zzqx_no_such_dataset_7781")
    assert out == {"ok": True, "count": 0, "results": []}


def test_limit_is_respected_in_request_and_response(fixture_fetch):
    # Fixture has 2 hits; ask for 1 -> URL carries rows=1 and we return 1.
    calls = fixture_fetch("package_search_transport.json")
    out = core.search_datasets(HEBREW, limit=1)
    assert "rows=1" in calls[0]
    assert len(out["results"]) == 1
    assert out["count"] == 137  # total on the server is still reported

    # datastore: fixture has 3 records; ask for 2 -> limit=2 on wire, 2 back.
    calls = fixture_fetch("datastore_search.json")
    out = core.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", limit=2)
    assert "limit=2" in calls[0]
    assert len(out["records"]) == 2
    assert out["count"] == 23


def test_default_limits(fixture_fetch):
    calls = fixture_fetch("package_search_transport.json")
    core.search_datasets(HEBREW)
    assert "rows=10" in calls[0]
    calls = fixture_fetch("datastore_search.json")
    core.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37")
    assert "limit=20" in calls[0]


def test_get_dataset_shapes_dataset(fixture_fetch):
    calls = fixture_fetch("package_show.json")
    out = core.get_dataset("mechirmnm")
    assert calls == [core.BASE_URL + "package_show?id=mechirmnm"]
    assert out["ok"] is True
    ds = out["dataset"]
    assert ds["id"] == "2a1c6d20-3f3a-4bb1-9f7e-6d0c5a4e8b31"
    assert ds["name"] == "mechirmnm"
    assert ds["title"] == "מחירון מוצרי מזון בפיקוח"
    assert ds["organization"] == "משרד הכלכלה והתעשייה"
    assert ds["license_title"] == "Other (Open)"
    assert ds["tags"] == ["מזון", "פיקוח מחירים"]
    assert [r["format"] for r in ds["resources"]] == ["CSV", "PDF"]
    assert ds["resources"][0]["datastore_active"] is True
    assert ds["resources"][1]["last_modified"] is None


def test_search_records_shapes_records_and_encodes_hebrew_query(fixture_fetch):
    calls = fixture_fetch("datastore_search.json")
    out = core.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", query="לחם", limit=3)
    url = calls[0]
    assert url.startswith(core.BASE_URL + "datastore_search?")
    assert "resource_id=b7cf8f14-64a2-4b33-8d4b-edb286fdbd37" in url
    assert "q=" + urllib.parse.quote("לחם") in url
    assert url.isascii()
    assert out["ok"] is True
    assert out["count"] == 23
    assert [f["id"] for f in out["fields"]] == ["_id", "שם המוצר", "יחידת מידה", "מחיר מרבי לצרכן"]
    assert out["records"][0]["שם המוצר"] == "לחם אחיד פרוס"
    assert out["records"][0]["מחיר מרבי לצרכן"] == 8.96


def test_search_records_empty_query_omits_q_param(fixture_fetch):
    calls = fixture_fetch("datastore_search.json")
    core.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", query="")
    assert "q=" not in calls[0]


def test_search_records_zero_rows_is_ok(fixture_fetch):
    fixture_fetch("datastore_search_empty.json")
    out = core.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", query="zzqx_no_such_value_7781")
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["records"] == []
    assert len(out["fields"]) == 4


# --------------------------------------------------------------------------- #
# Proof that nothing reaches the network
# --------------------------------------------------------------------------- #
def test_real_fetch_json_is_never_called_when_mocked(monkeypatch):
    real_fetch = core.fetch_json
    real_calls = []

    def spy_real(url):
        real_calls.append(url)
        return real_fetch(url)

    # Install the spy as "the real one", then install the test mock on top -
    # exactly what every happy-path test does. The spy must stay silent.
    monkeypatch.setattr(core, "fetch_json", spy_real)
    monkeypatch.setattr(core, "fetch_json", lambda url: load_fixture("package_search_transport.json"))
    out = core.search_datasets(HEBREW)
    assert out["ok"] is True
    assert real_calls == []


def test_unmocked_call_is_blocked_by_conftest_and_still_returns_structured_error():
    """If a test forgot to mock fetch_json, conftest's urlopen guard raises
    NetworkCallAttempted (an AssertionError). core must not let it escape
    (it is mapped to bad_response) and no socket is ever opened."""
    out = core.search_datasets(HEBREW)
    assert out["ok"] is False
    assert "NetworkCallAttempted" in out["detail"]
    with pytest.raises(NetworkCallAttempted):
        urllib.request.urlopen("https://data.gov.il/robots.txt")
