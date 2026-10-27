"""Pure functions for querying the data.gov.il CKAN action API.

Design rules (see README):
- stdlib only: urllib for HTTP, json for parsing.
- Every HTTP request goes through ONE function, ``fetch_json(url)``. Tests
  replace it with ``monkeypatch.setattr(core, "fetch_json", fake)``; the public
  functions look it up on the module at call time so the patch is honoured.
- No exception ever escapes a public function. Failures come back as
  ``{"ok": False, "error": <code>, "detail": <str>}``.
- Hebrew (and any non-ASCII) query text is percent-encoded with
  ``urllib.parse.quote`` before it reaches the wire.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

BASE_URL = "https://data.gov.il/api/3/action/"
USER_AGENT = "makor-il-open-data/0.1"
TIMEOUT_SECONDS = 10

# Input limits (documented in README).
MAX_QUERY_CHARS = 500
MAX_ID_CHARS = 200
MAX_LIMIT = 1000  # CKAN caps ``rows``/``limit`` at 1000 server-side.

# Error codes returned in the ``error`` field.
ERR_SOURCE_UNAVAILABLE = "source_unavailable"
ERR_BAD_RESPONSE = "bad_response"
ERR_INVALID_INPUT = "invalid_input"
ERR_NOT_FOUND = "not_found"


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #
def build_url(action: str, params: Dict[str, Any]) -> str:
    """Build ``BASE_URL + action + ?query`` with values percent-encoded.

    ``quote_via=urllib.parse.quote`` encodes spaces as ``%20`` and every
    non-ASCII byte (Hebrew included) as ``%XX`` UTF-8 escapes.
    """
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    query = urllib.parse.urlencode(clean, quote_via=urllib.parse.quote)
    return f"{BASE_URL}{action}?{query}" if query else f"{BASE_URL}{action}"


def fetch_json(url: str) -> Any:
    """Perform one GET request and return the parsed JSON body.

    This is the ONLY place in the module that touches the network. It raises
    (``urllib.error.HTTPError``, ``urllib.error.URLError``, ``TimeoutError``,
    ``json.JSONDecodeError``, ``UnicodeDecodeError``); callers map those to
    structured errors in ``_call``.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _error(code: str, detail: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "error": code}
    if detail:
        out["detail"] = str(detail)[:500]
    return out


def _call(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call one CKAN action and return either the ``result`` payload wrapped in
    ``{"ok": True, "result": ...}`` or a structured error dict.
    """
    url = build_url(action, params)
    try:
        # Module-global name, resolved at call time -> monkeypatch-friendly.
        payload = fetch_json(url)
    except urllib.error.HTTPError as exc:  # HTTPError before URLError (subclass)
        if exc.code == 404:
            return _error(ERR_NOT_FOUND, f"HTTP 404 for {action}")
        if exc.code >= 500 or exc.code == 429:
            return _error(ERR_SOURCE_UNAVAILABLE, f"HTTP {exc.code}")
        return _error(ERR_BAD_RESPONSE, f"HTTP {exc.code}")
    except (urllib.error.URLError, socket.timeout, TimeoutError,
            ConnectionError, OSError) as exc:
        return _error(ERR_SOURCE_UNAVAILABLE, getattr(exc, "reason", None) or repr(exc))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _error(ERR_BAD_RESPONSE, f"invalid JSON: {exc}")
    except Exception as exc:  # last line of defence: never raise outward
        return _error(ERR_BAD_RESPONSE, repr(exc))

    if not isinstance(payload, dict):
        return _error(ERR_BAD_RESPONSE, "top-level JSON is not an object")
    if payload.get("success") is not True:
        err = payload.get("error") or {}
        kind = err.get("__type", "") if isinstance(err, dict) else str(err)
        if "Not Found" in kind:
            return _error(ERR_NOT_FOUND, kind)
        if "Validation" in kind:
            return _error(ERR_INVALID_INPUT, json.dumps(err, ensure_ascii=False))
        return _error(ERR_BAD_RESPONSE, f"success=false: {kind or 'unknown'}")
    if "result" not in payload:
        return _error(ERR_BAD_RESPONSE, "missing 'result'")
    return {"ok": True, "result": payload["result"]}


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #
def _clean_text(value: Any, name: str, max_len: int, required: bool) -> Optional[str]:
    """Return a stripped string or raise ValueError with the reason."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name} is empty")
    if len(value) > max_len:
        raise ValueError(f"{name} longer than {max_len} characters")
    return value


def _clean_limit(limit: Any, default: int) -> int:
    if limit is None:
        return default
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


# --------------------------------------------------------------------------- #
# Shaping helpers
# --------------------------------------------------------------------------- #
def _shape_resource(res: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": res.get("id"),
        "format": res.get("format") or "",
        "url": res.get("url") or "",
    }


def _org_title(pkg: Dict[str, Any]) -> Optional[str]:
    org = pkg.get("organization")
    if isinstance(org, dict):
        return org.get("title") or org.get("name")
    return None


def _shape_search_hit(pkg: Dict[str, Any]) -> Dict[str, Any]:
    resources = pkg.get("resources") or []
    return {
        "id": pkg.get("id"),
        "title": pkg.get("title") or pkg.get("name") or "",
        "organization": _org_title(pkg),
        "resources": [_shape_resource(r) for r in resources if isinstance(r, dict)],
    }


def _shape_dataset(pkg: Dict[str, Any]) -> Dict[str, Any]:
    resources = pkg.get("resources") or []
    tags = pkg.get("tags") or []
    return {
        "id": pkg.get("id"),
        "name": pkg.get("name"),
        "title": pkg.get("title") or pkg.get("name") or "",
        "notes": pkg.get("notes") or "",
        "organization": _org_title(pkg),
        "license_title": pkg.get("license_title"),
        "metadata_modified": pkg.get("metadata_modified"),
        "tags": [t.get("display_name") or t.get("name") for t in tags if isinstance(t, dict)],
        "resources": [
            {
                "id": r.get("id"),
                "name": r.get("name") or "",
                "format": r.get("format") or "",
                "url": r.get("url") or "",
                "last_modified": r.get("last_modified"),
                "datastore_active": bool(r.get("datastore_active", False)),
            }
            for r in resources if isinstance(r, dict)
        ],
    }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def search_datasets(query: str, limit: int = 10) -> Dict[str, Any]:
    """Full-text search over datasets via ``package_search``."""
    try:
        q = _clean_text(query, "query", MAX_QUERY_CHARS, required=True)
        rows = _clean_limit(limit, 10)
    except ValueError as exc:
        return _error(ERR_INVALID_INPUT, str(exc))

    resp = _call("package_search", {"q": q, "rows": rows})
    if not resp["ok"]:
        return resp
    result = resp["result"]
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        return _error(ERR_BAD_RESPONSE, "package_search result malformed")
    hits = [_shape_search_hit(p) for p in result["results"] if isinstance(p, dict)]
    hits = hits[:rows]  # never hand back more than asked, even if the API does
    count = result.get("count")
    return {
        "ok": True,
        "count": count if isinstance(count, int) else len(hits),
        "results": hits,
    }


def get_dataset(dataset_id: str) -> Dict[str, Any]:
    """Fetch one dataset (id or name slug) via ``package_show``."""
    try:
        ident = _clean_text(dataset_id, "dataset_id", MAX_ID_CHARS, required=True)
    except ValueError as exc:
        return _error(ERR_INVALID_INPUT, str(exc))

    resp = _call("package_show", {"id": ident})
    if not resp["ok"]:
        return resp
    pkg = resp["result"]
    if not isinstance(pkg, dict):
        return _error(ERR_BAD_RESPONSE, "package_show result malformed")
    return {"ok": True, "dataset": _shape_dataset(pkg)}


def search_records(resource_id: str, query: str = "", limit: int = 20) -> Dict[str, Any]:
    """Search rows of a DataStore-enabled resource via ``datastore_search``.

    ``query`` may be empty (returns the first ``limit`` rows).
    """
    try:
        rid = _clean_text(resource_id, "resource_id", MAX_ID_CHARS, required=True)
        q = _clean_text(query, "query", MAX_QUERY_CHARS, required=False)
        lim = _clean_limit(limit, 20)
    except ValueError as exc:
        return _error(ERR_INVALID_INPUT, str(exc))

    resp = _call("datastore_search", {"resource_id": rid, "q": q, "limit": lim})
    if not resp["ok"]:
        return resp
    result = resp["result"]
    if not isinstance(result, dict) or not isinstance(result.get("records"), list):
        return _error(ERR_BAD_RESPONSE, "datastore_search result malformed")
    records: List[Dict[str, Any]] = result["records"][:lim]
    fields = [
        {"id": f.get("id"), "type": f.get("type")}
        for f in (result.get("fields") or []) if isinstance(f, dict)
    ]
    total = result.get("total")
    return {
        "ok": True,
        "count": total if isinstance(total, int) else len(records),
        "fields": fields,
        "records": records,
    }


__all__ = [
    "BASE_URL", "USER_AGENT", "TIMEOUT_SECONDS",
    "MAX_QUERY_CHARS", "MAX_ID_CHARS", "MAX_LIMIT",
    "build_url", "fetch_json",
    "search_datasets", "get_dataset", "search_records",
]
