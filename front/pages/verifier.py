import streamlit as st

from components import badge, card_end, card_start, field_row, page_title
from utils import ApiError, api_request, load_css

load_css()

page_title("Vérifier un certificat")

card_start("Vérifier un certificat")

tab_code, tab_file = st.tabs(["Par code", "Par fichier"])

result: dict | None = None
error_message: str | None = None

with tab_code:
    query_code = st.query_params.get("code", "")
    code = st.text_input(
        "Code du certificat", value=query_code, placeholder="ex : 3f9a1b2c4d5e6f7a..."
    )
    verify_code_clicked = st.button("Vérifier", key="oc-verify-code")

    auto_verify = bool(query_code) and not st.session_state.get("oc_query_verified")
    if auto_verify:
        st.session_state["oc_query_verified"] = True

    if verify_code_clicked or auto_verify:
        code_to_check = code.strip() if verify_code_clicked else query_code.strip()
        if not code_to_check:
            error_message = "Merci de saisir un code."
        else:
            try:
                response = api_request("GET", f"/api/verify/{code_to_check}")
                result = response.json()
            except ApiError as exc:
                error_message = (
                    "Certificat introuvable." if exc.status_code == 404 else exc.message
                )

with tab_file:
    uploaded_file = st.file_uploader("Déposez le fichier PDF du certificat", type=["pdf"])
    if st.button("Vérifier", key="oc-verify-file"):
        if uploaded_file is None:
            error_message = "Merci de sélectionner un fichier PDF."
        else:
            try:
                response = api_request(
                    "POST",
                    "/api/verify/file",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")},
                )
                result = response.json()
            except ApiError as exc:
                error_message = exc.message

card_end()

if error_message:
    card_start()
    st.markdown(badge("error", error_message), unsafe_allow_html=True)
    card_end()

if result:
    card_start()
    if result.get("status") == "authentique":
        st.markdown(badge("success", "Certificat authentique"), unsafe_allow_html=True)
        details = result.get("details", {})
        rows_html = "".join(
            [
                field_row("Nom", f'{details.get("name", "")} {details.get("first_name", "")}'),
                field_row("Événement", details.get("event_name", "")),
                field_row("Date", details.get("event_date", "")),
                field_row("Type", details.get("cert_type", "")),
                field_row("Émis le", details.get("generated_at", "")),
            ]
        )
        st.markdown(f'<div style="margin-top: 16px;">{rows_html}</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            badge("error", result.get("message", "Fichier non reconnu ou altéré.")),
            unsafe_allow_html=True,
        )
    card_end()
