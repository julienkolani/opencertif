import io

import qrcode
import streamlit as st

from components import badge, card_end, card_start, page_title
from utils import ApiError, api_request, load_css, require_roles

load_css()
auth = require_roles(["certifs-admin"])

page_title("Générer un certificat")

card_start("Informations du certificat")

available_types: list[str] = []
try:
    types_response = api_request("GET", "/api/templates", token=auth["token"])
    available_types = types_response.json().get("types", [])
except ApiError as exc:
    st.markdown(
        badge("error", f"Impossible de charger les types de certificat : {exc.message}"),
        unsafe_allow_html=True,
    )

name = st.text_input("Nom")
first_name = st.text_input("Prénom")
event_name = st.text_input("Événement")
event_date = st.date_input("Date de l'événement")
email = st.text_input("Email du destinataire (optionnel)")
send_email = st.checkbox(
    "Envoyer le certificat par email au destinataire",
    value=True,
    disabled=not email.strip(),
    help="Nécessite une adresse email ci-dessus.",
)
cert_type = st.selectbox("Type de certificat", available_types) if available_types else None

col_preview, col_generate = st.columns(2)
preview_clicked = col_preview.button("Prévisualiser", width="stretch")
generate_clicked = col_generate.button("Générer", width="stretch")

card_end()

if preview_clicked:
    card_start("Aperçu")
    if not cert_type:
        st.markdown(badge("error", "Aucun type de certificat disponible."), unsafe_allow_html=True)
    elif not (name.strip() and first_name.strip()):
        st.markdown(
            badge("warning", "Renseignez au moins le nom et le prénom pour prévisualiser."),
            unsafe_allow_html=True,
        )
    else:
        test_name = f"{first_name.strip()} {name.strip().upper()}"
        try:
            preview_response = api_request(
                "GET",
                f"/api/templates/{cert_type}/preview",
                token=auth["token"],
                params={"test_name": test_name},
            )
            st.image(preview_response.content, use_container_width=True)
        except ApiError as exc:
            st.markdown(
                badge("error", f"Erreur de prévisualisation : {exc.message}"), unsafe_allow_html=True
            )
    card_end()

if generate_clicked:
    missing = [
        label
        for label, value in [("nom", name), ("prénom", first_name), ("événement", event_name)]
        if not value.strip()
    ]

    card_start("Certificat")
    if missing:
        st.markdown(badge("warning", f"Champs manquants : {', '.join(missing)}."), unsafe_allow_html=True)
    elif not cert_type:
        st.markdown(badge("error", "Aucun type de certificat disponible."), unsafe_allow_html=True)
    else:
        try:
            response = api_request(
                "POST",
                "/api/certificates/generate",
                token=auth["token"],
                json={
                    "name": name.strip(),
                    "first_name": first_name.strip(),
                    "event_name": event_name.strip(),
                    "event_date": str(event_date),
                    "email": email.strip() if email else "",
                    "send_email": send_email and bool(email.strip()),
                    "cert_type": cert_type,
                },
            )
            body = response.json()

            st.markdown(badge("success", "Certificat généré avec succès"), unsafe_allow_html=True)
            if email.strip():
                if body.get("email_sent"):
                    st.markdown(badge("success", f"Email envoyé à {email.strip()}."), unsafe_allow_html=True)
                elif send_email:
                    st.markdown(
                        badge("warning", "Certificat généré mais l'email n'a pas pu être envoyé."),
                        unsafe_allow_html=True,
                    )

            qr_image = qrcode.make(body["qr_content"])
            qr_buffer = io.BytesIO()
            qr_image.save(qr_buffer, format="PNG")
            st.image(qr_buffer.getvalue(), width=160)

            pdf_response = api_request("GET", body["pdf_url"], token=auth["token"])
            st.download_button(
                "Télécharger le PDF",
                icon=":material/download:",
                data=pdf_response.content,
                file_name=f"{body['id']}.pdf",
                mime="application/pdf",
            )
        except ApiError as exc:
            if exc.status_code == 409:
                st.markdown(
                    badge("warning", "Un certificat existe déjà pour cette personne et cet événement."),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    badge("error", f"Erreur lors de la génération : {exc.message}"),
                    unsafe_allow_html=True,
                )
    card_end()
