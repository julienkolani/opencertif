import streamlit as st

from components import badge, card_end, card_start, page_title
from utils import ApiError, api_request, load_css, require_roles

load_css()
auth = require_roles(["certifs-admin"])

page_title("Gestion des Modèles (Templates)")

tab_list, tab_editor = st.tabs(["Liste & Ajout", "Éditeur Visuel"])

with tab_list:
    card_start("Ajouter un nouveau modèle")
    with st.form("add_template_form", clear_on_submit=True):
        new_cert_type = st.text_input("Identifiant du modèle (ex: devfest-2026, sans espaces)")
        uploaded_file = st.file_uploader("Fichier PDF de fond", type=["pdf"])
        submit = st.form_submit_button("Créer le modèle")

        if submit:
            if not new_cert_type.strip():
                st.markdown(badge("error", "L'identifiant est requis."), unsafe_allow_html=True)
            elif not uploaded_file:
                st.markdown(badge("error", "Le fichier PDF est requis."), unsafe_allow_html=True)
            elif " " in new_cert_type:
                st.markdown(
                    badge("error", "L'identifiant ne doit pas contenir d'espaces."), unsafe_allow_html=True
                )
            else:
                try:
                    # Pour un envoi multipart, api_request utilise requests derrière
                    # on peut passer "files" et "data" au lieu de "json"
                    api_request(
                        "POST",
                        "/api/templates",
                        token=auth["token"],
                        data={"cert_type": new_cert_type.strip()},
                        files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")},
                    )
                    st.markdown(
                        badge("success", "Modèle créé, direction l'éditeur visuel pour placer le texte."),
                        unsafe_allow_html=True,
                    )
                    st.session_state["oc_positions_type"] = None  # reset editor
                except ApiError as exc:
                    st.markdown(badge("error", f"Erreur : {exc.message}"), unsafe_allow_html=True)
    card_end()

    card_start("Modèles existants")
    try:
        available_types = api_request("GET", "/api/templates", token=auth["token"]).json().get("types", [])
        if not available_types:
            st.markdown('<p class="oc-table-empty">Aucun modèle existant.</p>', unsafe_allow_html=True)
        else:
            for c_type in available_types:
                col1, col2 = st.columns([0.8, 0.2])
                col1.write(f"**{c_type}**")
                if col2.button(
                    "Supprimer", key=f"oc-danger-del-{c_type}", icon=":material/delete:", width="stretch"
                ):
                    try:
                        api_request("DELETE", f"/api/templates/{c_type}", token=auth["token"])
                        st.session_state["oc_positions_type"] = None  # reset editor
                        st.toast(f"Modèle « {c_type} » supprimé.", icon=":material/check:")
                        st.rerun()
                    except ApiError as exc:
                        st.markdown(badge("error", f"Erreur : {exc.message}"), unsafe_allow_html=True)
                st.markdown('<hr style="border-color: var(--oc-border);" />', unsafe_allow_html=True)
    except ApiError as exc:
        st.markdown(badge("error", f"Impossible de charger les types : {exc.message}"), unsafe_allow_html=True)
    card_end()

with tab_editor:
    card_start("Sélectionner un modèle à éditer")
    available_types = []
    try:
        available_types = api_request("GET", "/api/templates", token=auth["token"]).json().get("types", [])
    except ApiError as exc:
        st.markdown(
            badge("error", f"Impossible de charger les types de certificat : {exc.message}"),
            unsafe_allow_html=True,
        )

    cert_type = st.selectbox("Type", available_types) if available_types else None
    card_end()

    if cert_type:
        if st.session_state.get("oc_positions_type") != cert_type:
            try:
                loaded_config = api_request(
                    "GET", f"/api/templates/{cert_type}", token=auth["token"]
                ).json()
                st.session_state["oc_positions_type"] = cert_type
                st.session_state["oc_positions_config"] = loaded_config
            except ApiError as exc:
                card_start()
                st.markdown(
                    badge("error", f"Impossible de charger la configuration : {exc.message}"),
                    unsafe_allow_html=True,
                )
                card_end()
                st.stop()

        config = st.session_state.get("oc_positions_config")
        if config:
            col_controls, col_preview = st.columns([1, 1.3])

            with col_controls:
                card_start("Réglages")
                test_name = st.text_input(
                    "Nom de test (long, pour tester le wrapping)",
                    value="Jean-Baptiste Kokou Mawuli AGBODJOGBE-HOUNSOUNOU",
                )
                x = st.slider("Position X du nom", 0, 1200, int(config["name_position"]["x"]))
                y = st.slider("Position Y du nom", 0, 900, int(config["name_position"]["y"]))
                name_max_size = st.slider("Taille de police max", 8, 100, int(config["name_max_size"]))
                name_min_size = st.slider("Taille de police min", 8, 100, int(config["name_min_size"]))
                name_max_width = st.slider("Largeur max du nom", 50, 1200, int(config["name_max_width"]))
                qr_x = st.slider("Position X du QR", 0, 1200, int(config["qr_position"]["x"]))
                qr_y = st.slider("Position Y du QR", 0, 900, int(config["qr_position"]["y"]))
                qr_size = st.slider("Taille du QR", 20, 300, int(config["qr_size"]))

                save_clicked = st.button("Enregistrer", width="stretch", key="save_pos")
                card_end()

            with col_preview:
                card_start("Aperçu")
                try:
                    preview_response = api_request(
                        "GET",
                        f"/api/templates/{cert_type}/preview",
                        token=auth["token"],
                        params={
                            "test_name": test_name.strip() or " ",
                            "x": x,
                            "y": y,
                            "name_max_size": name_max_size,
                            "name_min_size": name_min_size,
                            "name_max_width": name_max_width,
                            "qr_x": qr_x,
                            "qr_y": qr_y,
                            "qr_size": qr_size,
                        },
                    )
                    st.image(preview_response.content, width="stretch")
                except ApiError as exc:
                    st.markdown(
                        badge("error", f"Erreur de prévisualisation : {exc.message}"), unsafe_allow_html=True
                    )
                card_end()

            if save_clicked:
                updated_config = {
                    **config,
                    "name_position": {"x": x, "y": y},
                    "name_max_size": name_max_size,
                    "name_min_size": name_min_size,
                    "name_max_width": name_max_width,
                    "qr_position": {"x": qr_x, "y": qr_y},
                    "qr_size": qr_size,
                }
                card_start()
                try:
                    api_request("PUT", f"/api/templates/{cert_type}", token=auth["token"], json=updated_config)
                    st.session_state["oc_positions_config"] = updated_config
                    st.markdown(badge("success", "Positions enregistrées."), unsafe_allow_html=True)
                except ApiError as exc:
                    st.markdown(
                        badge("error", f"Échec de l'enregistrement : {exc.message}"), unsafe_allow_html=True
                    )
                card_end()
