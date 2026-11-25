import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

_FRONT_DIR = Path(__file__).resolve().parent

# Batch generation with emails costs ~1 to 2 s per recipient (one SMTP
# connection each): 30 s only covers a few dozen rows.
BATCH_TIMEOUT = 15 * 60


def get_api_url() -> str:
    return os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def load_css() -> None:
    """Injects style.css, then custom_theme.css if present (instance overrides)."""
    css_files = [_FRONT_DIR / "style.css", _FRONT_DIR / "custom_theme.css"]
    for css_file in css_files:
        if css_file.exists():
            st.markdown(f"<style>{css_file.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


class ApiError(Exception):
    """Raised by api_request() on a network failure or a non-2xx response."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def api_request(
    method: str, endpoint: str, token: str | None = None, timeout: float = 30, **kwargs: Any
) -> requests.Response:
    """Thin wrapper around `requests` targeting the OpenCertif API.

    timeout (seconds) defaults to 30; long server-side jobs pass more (see
    BATCH_TIMEOUT), otherwise the front reports a failure while the API is
    still generating, and the admin may resubmit the batch.

    Raises ApiError (with a French, user-facing message) on connection
    failure or a non-2xx response instead of letting callers deal with
    requests' native exceptions / status codes.
    """
    url = f"{get_api_url()}{endpoint}"
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
    except requests.exceptions.RequestException as exc:
        raise ApiError(f"Impossible de contacter l'API OpenCertif : {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text or f"Erreur HTTP {response.status_code}"
        if response.status_code == 401:
            _handle_expired_session()
        raise ApiError(str(detail), status_code=response.status_code)

    return response


def _handle_expired_session() -> None:
    """The API only ever returns 401 for a missing/invalid/expired Keycloak
    token (see api/core/auth.py; role mismatches are 403, not 401).

    st.user can stay "logged in" long after its access token has expired, so
    without this every page would keep showing the same raw "Invalid or
    expired token" error on every rerun. Force an actual logout instead so
    the user lands back on the login screen and gets a fresh token.
    """
    if not st.session_state.get("oc_auth", {}).get("is_authenticated"):
        return  # not logged in from the app's own point of view: nothing to clear

    st.session_state.pop("oc_auth", None)
    st.session_state["oc_session_expired"] = True
    try:
        st.logout()
    except Exception:
        pass
    # st.logout() only queues a browser redirect for *after* this script run
    # finishes; it doesn't stop execution on its own, so without an explicit
    # rerun here the caller would fall through and still render the raw
    # ApiError. Forcing the rerun now (it clears st.user synchronously) makes
    # the app redraw as "logged out" immediately instead of flashing the error.
    st.rerun()


# --- Session / auth -------------------------------------------------------
#
# Populated once in app.py (from st.user after st.login(), see section 7.6 of
# the cahier des charges) and read from every page via get_auth(). Kept here
# because it's small, session_state-driven glue the pages all depend on.

_DEFAULT_AUTH: dict[str, Any] = {
    "is_authenticated": False,
    "username": None,
    "roles": [],
    "token": None,
}


def token_seconds_remaining(token: str | None) -> float | None:
    """Best-effort read of a JWT's `exp` claim, without verifying its
    signature (the API always verifies it for real on every call; this is
    only used client-side to warn the user before their next action gets
    rejected with a 401, since Streamlit's st.login()/st.user never
    silently refreshes the access token on its own).
    """
    if not token:
        return None
    try:
        payload_segment = token.split(".")[1]
        padded = payload_segment + "=" * (-len(payload_segment) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        exp = claims.get("exp")
        return None if exp is None else exp - time.time()
    except Exception:
        return None


def get_auth() -> dict[str, Any]:
    return st.session_state.get("oc_auth", _DEFAULT_AUTH)


def require_roles(allowed_roles: list[str]) -> dict[str, Any]:
    """Guards a page: an authenticated user without any of `allowed_roles`,
    or a logged-out visitor, is redirected to a page they can actually see
    instead of being shown a dead-end "access denied" card: Historique for
    any signed-in certifs role, otherwise the public Vérifier page (the only
    one shown once logged out, alongside "Se connecter" in the sidebar).
    """
    auth = get_auth()
    if auth["is_authenticated"] and set(allowed_roles) & set(auth["roles"]):
        return auth

    st.session_state["oc_access_denied"] = True
    if auth["is_authenticated"] and set(auth["roles"]) & {"certifs-admin", "certifs-viewer"}:
        st.switch_page("pages/historique.py")
    else:
        st.switch_page("pages/verifier.py")

    return auth  # unreachable: st.switch_page() never returns
