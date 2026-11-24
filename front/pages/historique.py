from datetime import date

import streamlit as st

from components import badge, card_end, card_start, page_title
from utils import ApiError, api_request, load_css, require_roles

load_css()
auth = require_roles(["certifs-admin", "certifs-viewer"])
is_admin = "certifs-admin" in auth["roles"]

page_title("Historique des certificats")

# --- Filtres -----------------------------------------------------------

available_types: list[str] = []
try:
    available_types = api_request("GET", "/api/templates", token=auth["token"]).json().get("types", [])
except ApiError as exc:
    st.markdown(
        badge("error", f"Impossible de charger les types de certificat : {exc.message}"),
        unsafe_allow_html=True,
    )

current_year = date.today().year
year_options = ["Toutes"] + [str(y) for y in range(current_year + 1, current_year - 6, -1)]

card_start("Filtres")
col_search, col_type, col_year = st.columns(3)
with col_search:
    search = st.text_input("Recherche (nom, événement)")
with col_type:
    type_filter = st.selectbox("Type", ["Tous"] + available_types)
with col_year:
    year_filter = st.selectbox("Année", year_options)
card_end()

filters_key = (search, type_filter, year_filter)
if st.session_state.get("oc_history_filters_key") != filters_key:
    st.session_state["oc_history_filters_key"] = filters_key
    st.session_state["oc_history_page"] = 1

page = st.session_state.get("oc_history_page", 1)
per_page = 20

# --- Données -------------------------------------------------------------

params: dict[str, str | int] = {"page": page, "per_page": per_page}
if search.strip():
    params["search"] = search.strip()
if type_filter != "Tous":
    params["cert_type"] = type_filter
if year_filter != "Toutes":
    params["year"] = year_filter

card_start()

try:
    response = api_request("GET", "/api/history", token=auth["token"], params=params)
    body = response.json()
except ApiError as exc:
    body = {"items": [], "total": 0, "page": page, "per_page": per_page}
    st.markdown(badge("error", f"Impossible de charger l'historique : {exc.message}"), unsafe_allow_html=True)

items = body["items"]
total = body["total"]
total_pages = max(1, (total + per_page - 1) // per_page)

if not items:
    st.markdown('<p class="oc-table-empty">Aucun certificat trouvé.</p>', unsafe_allow_html=True)
else:
    header_labels = ["Nom", "Prénom", "Événement", "Date", "Type", "Généré le"]
    if is_admin:
        header_labels.append("")
    st.markdown(
        '<div style="display:flex; gap:8px; padding:10px 14px; background:var(--oc-bg-secondary); '
        'border-radius:8px; font-size:12px; font-weight:600; text-transform:uppercase; '
        'color:var(--oc-text-secondary); margin-bottom:4px;">'
        + "".join(f'<div style="flex:1;">{label}</div>' for label in header_labels)
        + "</div>",
        unsafe_allow_html=True,
    )

    for cert in items:
        cols = st.columns([2, 2, 3, 1.3, 1.6, 2, 1] if is_admin else [2, 2, 3, 1.3, 1.6, 2])
        cols[0].write(cert["name"])
        cols[1].write(cert["first_name"])
        cols[2].write(cert["event_name"])
        cols[3].write(cert["event_date"])
        cols[4].write(cert["cert_type"])
        cols[5].write(cert["generated_at"][:10])

        if is_admin:
            cache_key = f"oc_pdf_bytes_{cert['id']}"
            if cache_key in st.session_state:
                cols[6].download_button(
                    "Télécharger",
                    icon=":material/download:",
                    data=st.session_state[cache_key],
                    file_name=f"{cert['id']}.pdf",
                    mime="application/pdf",
                    key=f"oc-dl-{cert['id']}",
                    width="stretch",
                )
            else:
                if cols[6].button(
                    "Télécharger",
                    icon=":material/download:",
                    key=f"oc-fetch-{cert['id']}",
                    width="stretch",
                ):
                    try:
                        pdf_response = api_request(
                            "GET", f"/api/certificates/{cert['id']}/pdf", token=auth["token"]
                        )
                        st.session_state[cache_key] = pdf_response.content
                        st.rerun()
                    except ApiError as exc:
                        st.markdown(badge("error", exc.message), unsafe_allow_html=True)
        st.markdown(
            '<hr style="margin:4px 0; border-color: var(--oc-border);" />', unsafe_allow_html=True
        )

card_end()

# --- Pagination ----------------------------------------------------------

if items:
    card_start()
    col_prev, col_label, col_next = st.columns([1, 3, 1])
    with col_prev:
        if st.button("Précédent", key="oc-ghost-prev", disabled=page <= 1, width="stretch"):
            st.session_state["oc_history_page"] = page - 1
            st.rerun()
    with col_label:
        st.markdown(
            f'<p style="text-align:center; color:var(--oc-text-secondary); margin:8px 0;">'
            f"Page {page} / {total_pages} · {total} certificat(s)</p>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button(
            "Suivant", key="oc-ghost-next", disabled=page >= total_pages, width="stretch"
        ):
            st.session_state["oc_history_page"] = page + 1
            st.rerun()
    card_end()
