import base64
import json
import os

from pathlib import Path
from typing import Any

import streamlit as st

from components import badge
from utils import load_css, token_seconds_remaining

st.set_page_config(page_title="OpenCertif", layout="wide")
load_css()

_FRONT_DIR = Path(__file__).resolve().parent


def _extract_auth_state() -> dict[str, Any]:
    """Reads Streamlit's native OIDC user (st.login/st.user, wired to
    Keycloak, see cahier des charges section 7.6) into a small, stable
    shape the rest of the app consumes via utils.get_auth().

    Defensive on purpose: st.user's exact claim set depends on how the
    Keycloak client/realm is configured (e.g. whether realm_access is
    mapped into the ID token), and `st.login()`/`st.user` raise if
    `.streamlit/secrets.toml` has no [auth] section configured yet (fresh
    checkouts, local dev). Falling back to "not authenticated" instead of
    crashing keeps the app usable for the public /verifier page regardless.
    """
    try:
        user = st.user
    except Exception:
        return {"is_authenticated": False, "username": None, "roles": [], "token": None}

    if not getattr(user, "is_logged_in", False):
        return {"is_authenticated": False, "username": None, "roles": [], "token": None}

    def _claim(key: str) -> Any:
        try:
            return user.get(key)
        except Exception:
            return getattr(user, key, None)

    username = _claim("preferred_username") or _claim("name") or _claim("email")

    roles: list[str] = []
    realm_access = _claim("realm_access")
    if isinstance(realm_access, dict):
        roles = list(realm_access.get("roles", []))

    # st.user.tokens uses keys "access" and "id" (not "access_token"/"id_token")
    token = None
    try:
        tokens_proxy = getattr(user, "tokens", None)
        if tokens_proxy is not None:
            token = tokens_proxy["access"] if "access" in tokens_proxy else None
            if not token:
                token = tokens_proxy["id"] if "id" in tokens_proxy else None
    except Exception:
        pass

    # Keycloak only puts realm_access in the *access* token by default, not
    # in the ID token that st.user exposes; without this fallback an admin
    # logs in with roles=[] and only sees the public Vérifier page. Reading
    # the payload unverified is fine here: the API verifies the signature on
    # every call, this only decides which pages to show.
    if not roles and token:
        try:
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            roles = list(claims.get("realm_access", {}).get("roles", []))
        except Exception:
            pass

    return {
        "is_authenticated": True,
        "username": username,
        "roles": roles,
        "token": token,
    }


auth = _extract_auth_state()

# --- Fix rapide pour tester (DEV_MODE) ---
if os.getenv("DEV_MODE", "false").lower() in ("true", "1"):
    auth = {
        "is_authenticated": True,
        "username": "dev-admin",
        "roles": ["certifs-admin", "certifs-viewer"],
        "token": None,
    }
# --- Fin de l'ajout ---

st.session_state["oc_auth"] = auth

is_admin = "certifs-admin" in auth["roles"]
is_viewer = "certifs-viewer" in auth["roles"]

verifier_page = st.Page("pages/verifier.py", title="Vérifier", url_path="verifier")
generer_page = st.Page("pages/generer.py", title="Générer", url_path="generer")
batch_page = st.Page("pages/batch.py", title="Batch", url_path="batch")
historique_page = st.Page("pages/historique.py", title="Historique", url_path="historique")
# pages/templates.py: template list plus the visual position editor.
templates_page = st.Page("pages/templates.py", title="Modèles", url_path="modeles")
emails_page = st.Page("pages/emails.py", title="Emails", url_path="emails")

nav_items: list[tuple[Any, str]] = []
if is_admin:
    nav_items.append((generer_page, ":material/add_circle:"))
    nav_items.append((batch_page, ":material/layers:"))
if is_admin or is_viewer:
    nav_items.append((historique_page, ":material/list:"))
if is_admin:
    nav_items.append((templates_page, ":material/tune:"))
    nav_items.append((emails_page, ":material/mail:"))

# The verifier page is always reachable: it's the only page when logged out.
nav_items.append((verifier_page, ":material/search:"))

pages = [page for page, _icon in nav_items]
if not auth["is_authenticated"]:
    pages = [verifier_page]

pg = st.navigation(pages, position="hidden")

with st.sidebar:
    logo_path = _FRONT_DIR / "static" / "logo.png"
    brand_html = '<div class="oc-sidebar-brand">'
    if logo_path.exists():
        brand_html += f'<img src="app/static/logo.png" alt="Logo" />'
    brand_html += '<span class="oc-sidebar-brand-name">OpenCertif</span></div>'
    st.markdown(brand_html, unsafe_allow_html=True)

    if auth["is_authenticated"]:
        st.markdown('<div class="oc-sidebar-section-label">Navigation</div>', unsafe_allow_html=True)
        for page, material_icon in nav_items:
            st.page_link(page, label=page.title, icon=material_icon)

        st.markdown("<hr/>", unsafe_allow_html=True)

        role_label = "admin" if is_admin else "viewer"
        with st.container(key="oc-sidebar-user"):
            user_icon_col, user_text_col = st.columns([0.18, 0.82], vertical_alignment="center")
            with user_icon_col:
                st.markdown(":material/person:")
            with user_text_col:
                st.markdown(
                    f'<div class="oc-sidebar-user-name">{auth["username"] or "Utilisateur"}</div>'
                    f'<div class="oc-sidebar-user-role">Rôle : {role_label}</div>',
                    unsafe_allow_html=True,
                )

        remaining = token_seconds_remaining(auth["token"])
        if remaining is not None and remaining < 300:
            minutes_left = max(0, int(remaining // 60))
            st.markdown(
                badge(
                    "warning",
                    f"Session expire dans {minutes_left} min" if minutes_left else "Session expire bientôt",
                ),
                unsafe_allow_html=True,
            )
            if st.button("Prolonger la session", icon=":material/refresh:", width="stretch"):
                try:
                    st.login()
                except Exception:
                    pass

        if st.button("Déconnexion", icon=":material/logout:", width="stretch"):
            try:
                st.logout()
            except Exception:
                st.session_state.pop("oc_auth", None)
                st.rerun()
    else:
        st.markdown(
            '<div class="oc-sidebar-section-label">Espace organisateur</div>',
            unsafe_allow_html=True,
        )
        if st.session_state.pop("oc_session_expired", False):
            st.markdown(
                badge("warning", "Session expirée, merci de vous reconnecter."),
                unsafe_allow_html=True,
            )
        if st.button("Se connecter", width="stretch"):
            try:
                st.login()
            except Exception as exc:
                st.error(
                    "Authentification non configurée sur cette instance "
                    f"(.streamlit/secrets.toml manquant ou incomplet) : {exc}"
                )

if st.session_state.pop("oc_access_denied", False):
    st.markdown(
        badge("warning", "Vous n'avez pas les droits nécessaires pour accéder à cette page."),
        unsafe_allow_html=True,
    )

pg.run()
