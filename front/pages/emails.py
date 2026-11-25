import streamlit as st
import streamlit.components.v1 as components
from datetime import date

from components import badge, card_end, card_start, field_row, page_title
from utils import ApiError, api_request, load_css, require_roles

load_css()
auth = require_roles(["certifs-admin"])

page_title("Gestion des emails")

tab_config, tab_send, tab_history, tab_log = st.tabs([
    ":material/settings: Configuration SMTP",
    ":material/send: Envoyer",
    ":material/history: Historique",
    ":material/receipt_long: Journal des envois",
])


# --- Onglet Configuration SMTP ---
with tab_config:
    card_start("Paramètres du serveur SMTP")
    
    # Load current config
    if "email_config" not in st.session_state:
        try:
            resp = api_request("GET", "/api/email/config", token=auth["token"])
            st.session_state.email_config = resp.json()
        except ApiError:
            st.session_state.email_config = {}

    config = st.session_state.email_config

    host = st.text_input("Hôte SMTP", value=config.get("host", ""))
    
    col1, col2 = st.columns(2)
    port = col1.number_input("Port", value=config.get("port", 587), min_value=1, max_value=65535)
    
    sec_opts = ["starttls", "ssl", "none"]
    curr_sec = config.get("security", "starttls")
    sec_idx = sec_opts.index(curr_sec) if curr_sec in sec_opts else 0
    security = col2.selectbox("Sécurité", sec_opts, index=sec_idx)

    user = st.text_input("Utilisateur", value=config.get("user", ""))
    password = st.text_input("Mot de passe", type="password", placeholder="(inchangé si vide)")
    from_addr = st.text_input("Adresse expéditeur", value=config.get("from_addr", ""))
    
    email_subject = st.text_input("Sujet de l'email", value=config.get("email_subject", "Votre certificat : {evenement}"))
    st.caption("Variable disponible : `{evenement}`")

    email_template = st.text_area("Template HTML de l'email", value=config.get("email_template", ""), height=300)
    st.caption(
        "Laissez vide pour utiliser le template par défaut. Variables disponibles : "
        "`{prenom}`, `{nom}`, `{evenement}`, `{date}`, `{url_verification}`. "
        "L'aperçu et l'email de test utilisent le contenu affiché ci-dessus, "
        "même non sauvegardé."
    )
    # Sent with the preview and the test email so unsaved edits can be checked.
    draft_template = {"email_subject": email_subject, "email_template": email_template}

    col_save, col_test = st.columns(2)
    
    if col_save.button("Sauvegarder", width="stretch"):
        payload = {
            "host": host,
            "port": port,
            "security": security,
            "user": user,
            "from_addr": from_addr,
            "email_subject": email_subject,
            "email_template": email_template
        }
        if password:
            payload["password"] = password
            
        try:
            api_request("POST", "/api/email/config", json=payload, token=auth["token"])
            st.markdown(badge("success", "Configuration sauvegardée avec succès."), unsafe_allow_html=True)
            st.session_state.email_config.update(payload)
        except ApiError as e:
            st.markdown(badge("error", f"Erreur lors de la sauvegarde : {e.message}"), unsafe_allow_html=True)

    if col_test.button("Aperçu du template", width="stretch"):
        try:
            resp = api_request("POST", "/api/email/preview", json=draft_template, token=auth["token"])
            data = resp.json()
            st.markdown(f"**Sujet :** {data.get('subject', '')}")
            components.html(data.get('html', ''), height=400, scrolling=True)
        except ApiError as e:
            st.markdown(badge("error", f"Erreur de prévisualisation : {e.message}"), unsafe_allow_html=True)
            
    with st.expander("Tester l'envoi", icon=":material/science:"):
        test_email = st.text_input("Envoyer un mail de test à")
        if st.button("Envoyer le test"):
            if test_email:
                try:
                    resp = api_request("POST", "/api/email/test", json={"to_email": test_email, **draft_template}, token=auth["token"])
                    res_data = resp.json()
                    if res_data.get("ok"):
                        st.markdown(badge("success", "Email de test envoyé !"), unsafe_allow_html=True)
                    else:
                        st.markdown(badge("error", f"Erreur : {res_data.get('message', 'inconnue')}"), unsafe_allow_html=True)
                except ApiError as e:
                    st.markdown(badge("error", f"Erreur : {e.message}"), unsafe_allow_html=True)
            else:
                st.markdown(badge("warning", "Veuillez renseigner une adresse email."), unsafe_allow_html=True)

    card_end()

# --- Onglet Envoyer ---
with tab_send:
    card_start("Sélection des destinataires")
    
    send_mode = st.radio(
        "Mode de sélection",
        ["Tous les certificats", "Par événement", "Par type de certificat", "Par année"]
    )
    
    event_name = None
    cert_type = None
    year = None
    
    if send_mode == "Par événement":
        event_name = st.text_input("Nom de l'événement", key="send_event")
    elif send_mode == "Par type de certificat":
        available_types = []
        try:
            available_types = api_request("GET", "/api/templates", token=auth["token"]).json().get("types", [])
        except ApiError:
            pass
        if available_types:
            cert_type = st.selectbox("Type de certificat", available_types, key="send_type")
        else:
            st.markdown(badge("warning", "Aucun type de certificat disponible."), unsafe_allow_html=True)
    elif send_mode == "Par année":
        current_year = date.today().year
        year_int = st.selectbox("Année", list(range(current_year, current_year - 10, -1)), key="send_year")
        year = str(year_int)
        
    only_unsent = st.checkbox("Seulement les non encore envoyés", value=True)
    force_resend = st.checkbox("Forcer le renvoi (même si déjà envoyé)", value=False, disabled=only_unsent)
    
    card_end()
    
    if st.button("Envoyer", width="stretch", type="primary", icon=":material/send:"):
        payload = {
            "cert_ids": None,
            "event_name": event_name if send_mode == "Par événement" else None,
            "cert_type": cert_type if send_mode == "Par type de certificat" else None,
            "year": year if send_mode == "Par année" else None,
            "only_unsent": only_unsent,
            "force_resend": force_resend,
        }
        try:
            resp = api_request("POST", "/api/email/send", json=payload, token=auth["token"])
            st.session_state["oc_email_job"] = resp.json()
            st.rerun()
        except ApiError as e:
            st.markdown(badge("error", f"Erreur lors du lancement : {e.message}"), unsafe_allow_html=True)

    # Suivi du job en cours
    job = st.session_state.get("oc_email_job")
    if job and job.get("status") == "running":
        import time
        total = job.get("total", 0) or 0
        processed = job.get("processed", 0) or 0
        st.progress(
            min(processed / total, 1.0) if total else 0.0,
            text=f"Envoi en cours : {processed} / {total} certificat(s) traité(s)",
        )
        time.sleep(2)
        try:
            poll = api_request("GET", f"/api/email/send/{job['job_id']}", token=auth["token"])
            st.session_state["oc_email_job"] = poll.json()
        except ApiError as exc:
            # Never poll forever: an unknown job (404) or a persistent error
            # ends the follow-up with a message instead of spinning.
            if exc.status_code == 404:
                st.session_state["oc_email_job"] = {**job, "status": "interrupted"}
            else:
                failures = job.get("_poll_failures", 0) + 1
                st.session_state["oc_email_job"] = {
                    **job, "_poll_failures": failures, "status": "error" if failures >= 5 else "running",
                }
        st.rerun()

    if job and job.get("status") in ("interrupted", "error"):
        card_start("Rapport d'envoi")
        if job["status"] == "interrupted":
            message = (
                f"Envoi interrompu ({job.get('processed', 0)} / {job.get('total', 0)} traité(s)) : "
                "le serveur a redémarré pendant l'envoi."
            )
        else:
            message = "L'envoi s'est arrêté sur une erreur, ou son suivi est impossible."
        st.markdown(badge("error", message), unsafe_allow_html=True)
        st.caption(
            "Les emails déjà partis sont marqués comme envoyés et visibles dans le Journal des envois. "
            "Relancez avec « Seulement les non encore envoyés » pour terminer sans doublon."
        )
        if st.button("Nouvel envoi", icon=":material/refresh:", key="oc-email-job-reset-failed"):
            del st.session_state["oc_email_job"]
            st.rerun()
        card_end()

    if job and job.get("status") == "done":
        result = job.get("result", {})
        card_start("Rapport d'envoi")
        kind = "success" if result.get("sent", 0) > 0 else "warning"
        st.markdown(badge(kind, f"{result.get('sent', 0)} email(s) envoyé(s)"), unsafe_allow_html=True)
        st.markdown(
            field_row("Total sélectionné", str(result.get("total", 0)))
            + field_row("Envoyés", str(result.get("sent", 0)))
            + field_row("Ignorés (sans email ou déjà envoyés)", str(result.get("skipped", 0)))
            + field_row("Erreurs", str(len(result.get("errors", [])))),
            unsafe_allow_html=True,
        )
        if result.get("errors"):
            with st.expander(f"Détail des {len(result['errors'])} erreur(s)", icon=":material/error:"):
                for err in result["errors"]:
                    st.write(f"- {err.get('email', 'inconnu')} : {err.get('reason', '')}")
        if st.button("Nouvel envoi", icon=":material/refresh:"):
            del st.session_state["oc_email_job"]
            st.rerun()
        card_end()

# --- Onglet Historique ---
with tab_history:
    available_types = []
    try:
        available_types = api_request("GET", "/api/templates", token=auth["token"]).json().get("types", [])
    except ApiError:
        pass
        
    current_year = date.today().year
    year_options = ["Toutes"] + [str(y) for y in range(current_year + 1, current_year - 6, -1)]

    card_start("Filtres")
    col_search, col_type, col_year = st.columns(3)
    with col_search:
        search_query = st.text_input("Recherche (nom, événement)", key="email_hist_search")
    with col_type:
        hist_cert_type = st.selectbox("Type", ["Tous"] + available_types, key="email_hist_type")
    with col_year:
        hist_year = st.selectbox("Année", year_options, key="email_hist_year")
    card_end()
    
    filters_key = (search_query, hist_cert_type, hist_year)
    if st.session_state.get("oc_email_hist_filters_key") != filters_key:
        st.session_state["oc_email_hist_filters_key"] = filters_key
        st.session_state["oc_email_hist_page"] = 1

    page = st.session_state.get("oc_email_hist_page", 1)
    per_page = 20
    
    params = {"page": page, "per_page": per_page}
    if search_query.strip():
        params["search"] = search_query.strip()
    if hist_cert_type != "Tous":
        params["cert_type"] = hist_cert_type
    if hist_year != "Toutes":
        params["year"] = hist_year
        
    card_start()
    
    try:
        resp = api_request("GET", "/api/history", token=auth["token"], params=params)
        body = resp.json()
    except ApiError as exc:
        body = {"items": [], "total": 0, "page": page, "per_page": per_page}
        st.markdown(badge("error", f"Impossible de charger l'historique : {exc.message}"), unsafe_allow_html=True)

    items = body["items"]
    total = body["total"]
    total_pages = max(1, (total + per_page - 1) // per_page)
    
    if not items:
        st.markdown('<p class="oc-table-empty">Aucun certificat trouvé.</p>', unsafe_allow_html=True)
    else:
        header_labels = ["Nom", "Prénom", "Événement", "Email", "Envoyé le", "Action"]
        st.markdown(
            '<div style="display:flex; gap:8px; padding:10px 14px; background:var(--oc-bg-secondary); '
            'border-radius:8px; font-size:12px; font-weight:600; text-transform:uppercase; '
            'color:var(--oc-text-secondary); margin-bottom:4px;">'
            + "".join(f'<div style="flex:1;">{label}</div>' for label in header_labels)
            + "</div>",
            unsafe_allow_html=True,
        )

        for cert in items:
            cols = st.columns([1.5, 1.5, 2, 2, 1.5, 1])
            cols[0].write(cert.get("name", ""))
            cols[1].write(cert.get("first_name", ""))
            cols[2].write(cert.get("event_name", ""))
            cols[3].write(cert.get("email", "") or "-")
            cols[4].write(cert.get("email_sent_at", "")[:10] if cert.get("email_sent_at") else "Non envoyé")
            
            if cols[5].button("Renvoyer", key=f"email-resend-{cert['id']}", icon=":material/send:", help="Renvoyer l'email"):
                try:
                    api_request("POST", "/api/email/send", json={
                        "cert_ids": [cert["id"]],
                        "only_unsent": False,
                        "force_resend": True,
                    }, token=auth["token"])
                    st.toast("Email en cours d'envoi.", icon=":material/check:")
                except ApiError as e:
                    st.markdown(badge("error", f"Erreur : {e.message}"), unsafe_allow_html=True)
            
            st.markdown('<hr style="margin:4px 0; border-color: var(--oc-border);" />', unsafe_allow_html=True)

    card_end()
    
    # --- Pagination ---
    if items:
        card_start()
        col_prev, col_label, col_next = st.columns([1, 3, 1])
        with col_prev:
            if st.button("Précédent", key="oc-email-ghost-prev", disabled=page <= 1, width="stretch"):
                st.session_state["oc_email_hist_page"] = page - 1
                st.rerun()
        with col_label:
            st.markdown(
                f'<p style="text-align:center; color:var(--oc-text-secondary); margin:8px 0;">'
                f"Page {page} / {total_pages} · {total} certificat(s)</p>",
                unsafe_allow_html=True,
            )
        with col_next:
            if st.button("Suivant", key="oc-email-ghost-next", disabled=page >= total_pages, width="stretch"):
                st.session_state["oc_email_hist_page"] = page + 1
                st.rerun()
        card_end()


# --- Onglet Journal des envois ---
# Every send attempt recorded by the API (api/core/mailer.py, record_email):
# OpenCertif sends through SMTP, which keeps no copy in the sender's mailbox.
_KIND_LABELS = {"": "Tous", "unitaire": "Unitaire", "batch": "Batch", "masse": "Envoi en masse", "test": "Test"}
_STATUS_LABELS = {"": "Tous", "envoye": "Envoyé", "echec": "Échec"}

with tab_log:
    card_start("Filtres")
    col_rcpt, col_evt, col_status, col_kind = st.columns([2, 2, 1, 1])
    log_recipient = col_rcpt.text_input("Destinataire", key="email_log_recipient")
    log_event = col_evt.text_input("Événement", key="email_log_event")
    log_status = col_status.selectbox(
        "Statut", list(_STATUS_LABELS), format_func=_STATUS_LABELS.get, key="email_log_status"
    )
    log_kind = col_kind.selectbox(
        "Type", list(_KIND_LABELS), format_func=_KIND_LABELS.get, key="email_log_kind"
    )
    card_end()

    log_filters = {
        key: value
        for key, value in {
            "recipient": log_recipient.strip(),
            "event_name": log_event.strip(),
            "status": log_status,
            "kind": log_kind,
        }.items()
        if value
    }
    log_filters_key = tuple(sorted(log_filters.items()))
    if st.session_state.get("oc_email_log_filters_key") != log_filters_key:
        st.session_state["oc_email_log_filters_key"] = log_filters_key
        st.session_state["oc_email_log_page"] = 1

    log_page = st.session_state.get("oc_email_log_page", 1)
    log_page_size = 50

    try:
        log_body = api_request(
            "GET", "/api/email/log", token=auth["token"],
            params={**log_filters, "page": log_page, "page_size": log_page_size},
        ).json()
    except ApiError as exc:
        log_body = {"items": [], "total": 0}
        st.markdown(badge("error", f"Impossible de charger le journal : {exc.message}"), unsafe_allow_html=True)

    log_items = log_body["items"]
    log_total = log_body["total"]
    log_total_pages = max(1, (log_total + log_page_size - 1) // log_page_size)

    card_start()
    if not log_items:
        st.markdown('<p class="oc-table-empty">Aucun envoi enregistré.</p>', unsafe_allow_html=True)
        selected_log = None
    else:
        rows = [
            {
                "Date (UTC)": (item["sent_at"] or "")[:19].replace("T", " "),
                "Destinataire": item["recipient"],
                "Sujet": item["subject"] or "",
                "Type": _KIND_LABELS.get(item["kind"], item["kind"]),
                "Statut": _STATUS_LABELS.get(item["status"], item["status"]),
                "Erreur": item["error"] or "",
                "Envoyé par": item["sent_by"] or "",
            }
            for item in log_items
        ]
        st.caption("Cliquez sur une ligne pour afficher l'email envoyé.")
        event = st.dataframe(
            rows, hide_index=True, width="stretch",
            on_select="rerun", selection_mode="single-row", key="email_log_table",
        )
        selected_rows = event.selection.rows if event else []
        selected_log = log_items[selected_rows[0]] if selected_rows else None

        try:
            csv_bytes = api_request(
                "GET", "/api/email/log/export.csv", token=auth["token"], params=log_filters
            ).content
            st.download_button(
                "Exporter en CSV (filtres appliqués)", csv_bytes,
                file_name="journal-emails.csv", mime="text/csv", icon=":material/download:",
            )
        except ApiError as exc:
            st.markdown(badge("error", f"Export indisponible : {exc.message}"), unsafe_allow_html=True)
    card_end()

    if log_items and log_total_pages > 1:
        card_start()
        col_prev, col_label, col_next = st.columns([1, 3, 1])
        with col_prev:
            if st.button("Précédent", key="oc-email-log-ghost-prev", disabled=log_page <= 1, width="stretch"):
                st.session_state["oc_email_log_page"] = log_page - 1
                st.rerun()
        with col_label:
            st.markdown(
                f'<p style="text-align:center; color:var(--oc-text-secondary); margin:8px 0;">'
                f"Page {log_page} / {log_total_pages} · {log_total} envoi(s)</p>",
                unsafe_allow_html=True,
            )
        with col_next:
            if st.button("Suivant", key="oc-email-log-ghost-next", disabled=log_page >= log_total_pages, width="stretch"):
                st.session_state["oc_email_log_page"] = log_page + 1
                st.rerun()
        card_end()

    if selected_log:
        card_start("Détail de l'envoi")
        try:
            detail = api_request("GET", f"/api/email/log/{selected_log['id']}", token=auth["token"]).json()
        except ApiError as exc:
            detail = None
            st.markdown(badge("error", f"Impossible de charger l'envoi : {exc.message}"), unsafe_allow_html=True)
        if detail:
            st.write(f"**Destinataire :** {detail['recipient']}")
            st.write(f"**Sujet :** {detail['subject'] or ''}")
            st.write(
                f"**Statut :** {_STATUS_LABELS.get(detail['status'], detail['status'])}"
                f" · **Type :** {_KIND_LABELS.get(detail['kind'], detail['kind'])}"
                f" · **Par :** {detail['sent_by'] or '-'}"
            )
            if detail.get("cert_id"):
                st.write(f"**Certificat :** `{detail['cert_id']}` ({detail.get('event_name') or ''})")
            if detail.get("error"):
                st.markdown(badge("error", "Échec de l'envoi"), unsafe_allow_html=True)
                st.code(detail["error"], language=None)
            if detail.get("html_body"):
                components.html(detail["html_body"], height=500, scrolling=True)
        card_end()

