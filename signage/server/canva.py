"""Canva Connect: let the owner link their Canva account and import designs as images.

Flow: OAuth 2.0 authorization code + PKCE -> list designs -> export job (PNG) -> download.
NOTE: written from Canva's public documentation and exercised only against a fake Canva in
the tests. It has not been run against the real service yet.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"
API = "https://api.canva.com/rest/v1"
SCOPES = "design:meta:read design:content:read"
EXPORT_TIMEOUT = 60       # seconds to wait for Canva to render a design
MAX_PAGES = 10
MAX_BYTES = 25 * 1024 * 1024


class CanvaError(Exception):
    pass


class Canva:
    def __init__(self, store, redirect_uri: str, transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self.store, self.redirect_uri, self.sleep = store, redirect_uri, sleep
        self.http = httpx.Client(transport=transport, timeout=20, follow_redirects=False)

    # --- state ------------------------------------------------------------
    def configured(self) -> bool:
        return bool(self.store.get("canva_client_id") and self.store.get("canva_client_secret"))

    def connected(self) -> bool:
        return bool(self.store.get("canva_refresh_token"))

    def configure(self, client_id: str, client_secret: str) -> None:
        self.store.set("canva_client_id", client_id)
        self.store.set("canva_client_secret", client_secret)
        self.disconnect()

    def disconnect(self) -> None:
        for key in ("canva_access_token", "canva_refresh_token", "canva_expires", "canva_state", "canva_verifier"):
            self.store.set(key, "")

    # --- OAuth ------------------------------------------------------------
    def login_url(self) -> str:
        if not self.configured():
            raise CanvaError("קודם צריך להזין את פרטי החיבור ל-Canva")
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(24)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.store.set("canva_verifier", verifier)
        self.store.set("canva_state", state)
        return AUTHORIZE_URL + "?" + urlencode({
            "code_challenge": challenge, "code_challenge_method": "s256", "scope": SCOPES,
            "response_type": "code", "client_id": self.store.get("canva_client_id"),
            "state": state, "redirect_uri": self.redirect_uri,
        })

    def _token_request(self, form: dict) -> None:
        creds = f"{self.store.get('canva_client_id')}:{self.store.get('canva_client_secret')}".encode()
        try:
            r = self.http.post(API + "/oauth/token", data=form,
                               headers={"Authorization": "Basic " + base64.b64encode(creds).decode()})
        except httpx.HTTPError:
            raise CanvaError("אין חיבור ל-Canva. בדקו שיש אינטרנט") from None
        if r.status_code != 200:
            raise CanvaError("Canva דחתה את החיבור. בדקו את פרטי החיבור ונסו שוב")
        body = r.json()
        self.store.set("canva_access_token", body["access_token"])
        self.store.set("canva_expires", str(time.time() + int(body.get("expires_in", 3600)) - 60))
        if body.get("refresh_token"):  # refresh tokens are replaced on every use
            self.store.set("canva_refresh_token", body["refresh_token"])

    def finish_login(self, code: str, state: str) -> None:
        expected = self.store.get("canva_state")
        if not expected or not state or not secrets.compare_digest(expected, state):
            raise CanvaError("בקשת החיבור לא תקפה. התחילו מחדש")
        verifier = self.store.get("canva_verifier")
        self.store.set("canva_state", "")
        self.store.set("canva_verifier", "")
        self._token_request({"grant_type": "authorization_code", "code": code,
                             "code_verifier": verifier, "redirect_uri": self.redirect_uri})

    def _refresh(self) -> None:
        try:
            self._token_request({"grant_type": "refresh_token", "refresh_token": self.store.get("canva_refresh_token")})
        except CanvaError:
            self.disconnect()
            raise CanvaError("החיבור ל-Canva פג. צריך לחבר את החשבון מחדש") from None

    def _call(self, method: str, path: str, **kwargs) -> dict:
        if not self.connected():
            raise CanvaError("חשבון Canva לא מחובר")
        if time.time() >= float(self.store.get("canva_expires") or 0):
            self._refresh()
        for attempt in (1, 2):
            try:
                r = self.http.request(method, API + path, **kwargs,
                                      headers={"Authorization": "Bearer " + self.store.get("canva_access_token")})
            except httpx.HTTPError:
                raise CanvaError("אין חיבור ל-Canva. בדקו שיש אינטרנט") from None
            if r.status_code == 401 and attempt == 1:
                self._refresh()
                continue
            if r.status_code == 429:
                raise CanvaError("יותר מדי בקשות ל-Canva. נסו שוב בעוד דקה")
            if r.status_code >= 400:
                raise CanvaError(f"Canva החזירה שגיאה ({r.status_code})")
            return r.json()
        raise CanvaError("החיבור ל-Canva נכשל")

    # --- designs ------------------------------------------------------------
    def designs(self, continuation: str = "", query: str = "") -> dict:
        params = {"continuation": continuation} if continuation else ({"query": query} if query else {})
        body = self._call("GET", "/designs", params=params)
        items = [{"id": d["id"], "title": d.get("title") or "ללא שם",
                  "thumbnail": (d.get("thumbnail") or {}).get("url", "")} for d in body.get("items", [])]
        return {"items": items, "continuation": body.get("continuation", "")}

    def export_png(self, design_id: str) -> list[bytes]:
        """Ask Canva to render the design and return the PNG bytes of its pages."""
        job = self._call("POST", "/exports", json={"design_id": design_id, "format": {"type": "png"}})["job"]
        deadline = time.time() + EXPORT_TIMEOUT
        while job.get("status") == "in_progress":
            if time.time() > deadline:
                raise CanvaError("הייצוא מ-Canva לוקח יותר מדי זמן. נסו שוב")
            self.sleep(1.5)
            job = self._call("GET", f"/exports/{job['id']}")["job"]
        if job.get("status") != "success" or not job.get("urls"):
            raise CanvaError("Canva לא הצליחה לייצא את העיצוב")
        pages = []
        for url in job["urls"][:MAX_PAGES]:
            if not url.startswith("https://"):
                raise CanvaError("כתובת הורדה לא תקינה מ-Canva")
            try:
                with self.http.stream("GET", url) as r:
                    if r.status_code != 200:
                        raise CanvaError("הורדת העיצוב מ-Canva נכשלה")
                    data = b""
                    for chunk in r.iter_bytes():
                        data += chunk
                        if len(data) > MAX_BYTES:
                            raise CanvaError("העיצוב גדול מדי")
            except httpx.HTTPError:
                raise CanvaError("הורדת העיצוב מ-Canva נכשלה") from None
            pages.append(data)
        return pages
