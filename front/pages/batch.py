import datetime as _dt
import io

import openpyxl
import pandas as pd
import streamlit as st

from components import badge, card_end, card_start, field_row, page_title, upload_zone
from utils import ApiError, api_request, load_css, require_roles

load_css()
auth = require_roles(["certifs-admin"])

page_title("Génération par lot")

# name/first_name identify a person and must come from a column, one per row.
# event_name/event_date are very often the same for the whole file (one
# export per event) so they can also be set once for all rows instead.
STRICT_REQUIRED_FIELDS = [
    ("name", "Nom"),
    ("first_name", "Prénom"),
]

TEXT_COLUMNS = ["Nom", "Prénom", "Événement", "Date", "Type", "Email"]
GRID_COLUMNS = ["Sélection"] + TEXT_COLUMNS

# --- Étape 1 : fichier -----------------------------------------------------

card_start("1. Fichier Excel")
upload_zone("Glissez votre fichier Excel ici", "ou cliquez pour parcourir")
uploaded_file = st.file_uploader(
    "Fichier Excel", type=["xlsx", "xls"], label_visibility="collapsed"
)
card_end()

if uploaded_file is None:
    st.stop()

file_bytes = uploaded_file.getvalue()

try:
    workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
except Exception as exc:
    card_start()
    st.markdown(badge("error", f"Impossible de lire ce fichier Excel : {exc}"), unsafe_allow_html=True)
    card_end()
    st.stop()

if not rows:
    card_start()
    st.markdown(badge("error", "Le fichier est vide."), unsafe_allow_html=True)
    card_end()
    st.stop()

header = [str(cell).strip() if cell is not None else f"Colonne {i + 1}" for i, cell in enumerate(rows[0])]
data_rows = rows[1:]

# --- Étape 2 : mapping des colonnes ----------------------------------------

available_types: list[str] = []
try:
    available_types = api_request("GET", "/api/templates", token=auth["token"]).json().get("types", [])
except ApiError as exc:
    st.markdown(
        badge("error", f"Impossible de charger les types de certificat : {exc.message}"),
        unsafe_allow_html=True,
    )

card_start("2. Mapping des colonnes")

column_options = ["(non mappé)"] + header
mapping: dict[str, str] = {}

for field_key, field_label in STRICT_REQUIRED_FIELDS:
    choice = st.selectbox(field_label, column_options, key=f"oc-map-{field_key}")
    if choice != "(non mappé)":
        mapping[field_key] = choice

event_name_choice = st.selectbox("Événement", column_options, key="oc-map-event_name")
default_event_name: str | None = None
if event_name_choice != "(non mappé)":
    mapping["event_name"] = event_name_choice
else:
    default_event_name = st.text_input(
        "... ou appliquer cet événement à toutes les lignes", key="oc-default-event-name"
    ).strip() or None

event_date_choice = st.selectbox("Date", column_options, key="oc-map-event_date")
default_event_date: str | None = None
if event_date_choice != "(non mappé)":
    mapping["event_date"] = event_date_choice
else:
    default_event_date_input = st.date_input(
        "... ou appliquer cette date à toutes les lignes",
        value=None,
        key="oc-default-event-date",
    )
    default_event_date = str(default_event_date_input) if default_event_date_input else None

email_choice = st.selectbox("Email (optionnel)", column_options, key="oc-map-email")
if email_choice != "(non mappé)":
    mapping["email"] = email_choice

type_choice = st.selectbox("Colonne type (optionnel)", column_options, key="oc-map-type")
default_cert_type: str | None = None
if type_choice != "(non mappé)":
    mapping["cert_type"] = type_choice
elif available_types:
    default_cert_type = st.selectbox(
        "... ou appliquer ce type à toutes les lignes", available_types, key="oc-default-type"
    )

card_end()

missing_required = [label for key, label in STRICT_REQUIRED_FIELDS if key not in mapping]
if "event_name" not in mapping and not default_event_name:
    missing_required.append("Événement")
if "event_date" not in mapping and not default_event_date:
    missing_required.append("Date")

if missing_required:
    card_start()
    st.markdown(
        badge("warning", f"Mapping incomplet : {', '.join(missing_required)} manquant(s)."),
        unsafe_allow_html=True,
    )
    card_end()
    st.stop()

# A very easy mistake to make (Nom and Prénom sit next to each other in the
# dropdown): mapping both identity fields to the same source column silently
# loses the surname (every row ends up with Nom == Prénom), which then makes
# far more rows look like duplicates of each other than they really are.
if mapping.get("name") and mapping.get("name") == mapping.get("first_name"):
    card_start()
    st.markdown(
        badge(
            "warning",
            f"« Nom » et « Prénom » pointent tous les deux vers la colonne "
            f"« {mapping['name']} » : vérifiez le mapping, il manque probablement une colonne.",
        ),
        unsafe_allow_html=True,
    )
    card_end()


# --- Étape 3 : nettoyage & édition -----------------------------------------


def _stringify(value: object) -> str:
    """Normalizes a raw Excel cell (datetime, float, None, ...) to clean text."""
    if value is None:
        return ""
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    text = str(value).strip()
    # openpyxl gives whole numbers (e.g. a phone number) as floats like "123.0"
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        text = text[:-2]
    return text


def _coerce_selection_dtype(df: pd.DataFrame) -> pd.DataFrame:
    """Uses pandas' nullable "boolean" dtype for the Sélection column instead
    of plain bool: the grid must tolerate a checkbox cell being cleared to
    null (e.g. selecting it and hitting Delete/Backspace instead of clicking
    it); with a plain numpy bool column, Streamlit's data_editor crashes
    the instant that happens (TypeError: Invalid value 'nan' for dtype
    'bool'), because numpy bool has no way to represent a missing value.
    """
    df = df.copy()
    df["Sélection"] = df["Sélection"].astype("boolean")
    return df


def _build_seed_dataframe() -> pd.DataFrame:
    records = []
    for row in data_rows:
        row_dict = dict(zip(header, row))
        records.append(
            {
                "Sélection": False,
                "Nom": _stringify(row_dict.get(mapping.get("name", ""))),
                "Prénom": _stringify(row_dict.get(mapping.get("first_name", ""))),
                "Événement": (
                    _stringify(row_dict.get(mapping.get("event_name", "")))
                    if "event_name" in mapping
                    else (default_event_name or "")
                ),
                "Date": (
                    _stringify(row_dict.get(mapping.get("event_date", "")))
                    if "event_date" in mapping
                    else (default_event_date or "")
                ),
                "Type": (
                    _stringify(row_dict.get(mapping.get("cert_type", "")))
                    if "cert_type" in mapping
                    else (default_cert_type or "")
                ),
                "Email": _stringify(row_dict.get(mapping.get("email", ""))) if "email" in mapping else "",
            }
        )
    return _coerce_selection_dtype(pd.DataFrame(records, columns=GRID_COLUMNS))


def _clean_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    cleaned = df.copy()
    for col in TEXT_COLUMNS:
        cleaned[col] = cleaned[col].fillna("").astype(str).str.strip()
    cleaned["Sélection"] = cleaned["Sélection"].fillna(False)
    cleaned = _coerce_selection_dtype(cleaned)
    # A row with no Nom and no Prénom has nobody to generate a certificate
    # for: drop it regardless of Événement/Date/Type, which are very often
    # non-empty even on a blank source row (they can come from a
    # batch-wide default applied to every row, not just real ones).
    is_blank = (cleaned["Nom"] == "") & (cleaned["Prénom"] == "")
    dropped = int(is_blank.sum())
    cleaned = cleaned[~is_blank].reset_index(drop=True)
    return cleaned, dropped


fingerprint = (
    uploaded_file.name,
    len(file_bytes),
    tuple(sorted(mapping.items())),
    default_event_name,
    default_event_date,
    default_cert_type,
)

if st.session_state.get("oc_batch_fingerprint") != fingerprint:
    st.session_state["oc_batch_fingerprint"] = fingerprint
    st.session_state["oc_batch_df"] = _build_seed_dataframe()
    st.session_state["oc_batch_seed_version"] = st.session_state.get("oc_batch_seed_version", 0) + 1
    st.session_state.pop("oc_batch_preview", None)
    st.session_state.pop("oc_batch_preview_error", None)

card_start(f"3. Nettoyage & édition ({len(data_rows)} lignes importées)")

st.caption(
    "Corrigez, supprimez ou complétez des lignes directement dans le tableau, "
    "comme un prétraitement de dataset avant utilisation. Rien n'est envoyé tant que "
    "vous n'avez pas cliqué sur \"Générer\" à l'étape suivante."
)

editor_key = f"oc_batch_editor_v{st.session_state['oc_batch_seed_version']}"
edited_df = st.data_editor(
    st.session_state["oc_batch_df"],
    key=editor_key,
    num_rows="dynamic",
    width="stretch",
    height=min(36 * (len(st.session_state["oc_batch_df"]) + 1) + 20, 500),
    column_config={
        "Sélection": st.column_config.CheckboxColumn(
            "",
            help="Cocher pour agir juste sur cette ligne (aperçu / suppression / génération)",
            pinned=True,
            default=False,
        ),
    },
)

# Must read `edited_df` here, NOT st.session_state["oc_batch_df"]: the
# latter is only the baseline fed *into* the editor above and is never
# updated by the user's own edits (those live in Streamlit's widget state
# until an action like this one reads the editor's return value). Cleaning
# from the stale baseline would silently discard any manual fix the admin
# just made in the grid.
if st.button("Nettoyer (espaces + lignes vides)", icon=":material/cleaning_services:"):
    cleaned_df, dropped = _clean_dataframe(edited_df)
    st.session_state["oc_batch_df"] = cleaned_df
    st.session_state["oc_batch_seed_version"] += 1
    st.toast(f"{dropped} ligne(s) vide(s) supprimée(s)." if dropped else "Rien à nettoyer.", icon=":material/check:")
    st.rerun()

# Recompute status from the CURRENT edited state (the actual return value
# above) rather than baking a "Statut" column into the grid itself: Streamlit
# replays the user's edit-diff on top of whatever `data=` we pass on every
# rerun, so a status column computed before that replay would show stale
# values for whichever cells the diff overwrites.
normalized = edited_df.copy()
for col in TEXT_COLUMNS:
    if col not in normalized.columns:
        normalized[col] = ""
    normalized[col] = normalized[col].fillna("").astype(str).str.strip()
if "Sélection" not in normalized.columns:
    normalized["Sélection"] = False
normalized["Sélection"] = normalized["Sélection"].fillna(False).astype(bool)

available_types_set = set(available_types)
statuses: list[str] = []
seen_keys: set[tuple[str, str, str, str]] = set()
incomplete_rows: list[int] = []
unknown_type_rows: list[int] = []
duplicate_rows: list[int] = []

for position, row in enumerate(normalized[GRID_COLUMNS].itertuples(index=False), start=1):
    _selected, nom, prenom, evenement, date_val, type_val, _email = row
    if not all([nom, prenom, evenement, date_val]):
        statuses.append("Incomplet")
        incomplete_rows.append(position)
    elif not type_val or (available_types_set and type_val not in available_types_set):
        statuses.append("Type inconnu")
        unknown_type_rows.append(position)
    else:
        key = (nom.lower(), prenom.lower(), evenement.lower(), date_val.lower())
        if key in seen_keys:
            statuses.append("Doublon")
            duplicate_rows.append(position)
        else:
            seen_keys.add(key)
            statuses.append("OK")

selected_positions = [i + 1 for i, sel in enumerate(normalized["Sélection"]) if sel]
selected_count = len(selected_positions)

col_preview_sel, col_delete_sel = st.columns(2)

with col_preview_sel:
    if st.button(
        f"Aperçu ({selected_count})",
        icon=":material/visibility:",
        disabled=selected_count == 0,
        width="stretch",
        help="Aperçu du certificat pour la 1ère ligne cochée",
    ):
        first_row = normalized.iloc[selected_positions[0] - 1]
        cert_type_for_preview = first_row["Type"]
        test_name = f'{first_row["Prénom"]} {first_row["Nom"].upper()}'.strip()
        st.session_state.pop("oc_batch_preview_error", None)
        st.session_state.pop("oc_batch_preview", None)
        if not cert_type_for_preview:
            st.session_state["oc_batch_preview_error"] = "Cette ligne n'a pas de type de certificat."
        else:
            try:
                preview_response = api_request(
                    "GET",
                    f"/api/templates/{cert_type_for_preview}/preview",
                    token=auth["token"],
                    params={"test_name": test_name or " "},
                )
                st.session_state["oc_batch_preview"] = preview_response.content
            except ApiError as exc:
                st.session_state["oc_batch_preview_error"] = exc.message

with col_delete_sel:
    if st.button(
        f"Supprimer la sélection ({selected_count})",
        key="oc-danger-delete-selection",
        icon=":material/delete:",
        disabled=selected_count == 0,
        width="stretch",
    ):
        remaining_df = normalized[~normalized["Sélection"]][GRID_COLUMNS].reset_index(drop=True)
        st.session_state["oc_batch_df"] = _coerce_selection_dtype(remaining_df)
        st.session_state["oc_batch_seed_version"] += 1
        st.session_state.pop("oc_batch_preview", None)
        st.session_state.pop("oc_batch_preview_error", None)
        st.toast(f"{selected_count} ligne(s) supprimée(s).", icon=":material/check:")
        st.rerun()

preview_error = st.session_state.get("oc_batch_preview_error")
preview_bytes = st.session_state.get("oc_batch_preview")
if preview_error:
    st.markdown(badge("error", f"Aperçu impossible : {preview_error}"), unsafe_allow_html=True)
elif preview_bytes:
    st.image(preview_bytes, width="stretch", caption="Aperçu de la 1ère ligne cochée")

ok_count = statuses.count("OK")
st.caption(
    f"{ok_count} ligne(s) prête(s) · {len(duplicate_rows)} doublon(s) probable(s) · "
    f"{len(incomplete_rows)} incomplète(s) · {len(unknown_type_rows)} type(s) inconnu(s) "
    "(estimation avant envoi : le serveur revérifie tout, notamment les doublons déjà en base)."
)

if duplicate_rows:
    with st.expander(f"{len(duplicate_rows)} doublon(s) probable(s) (même nom/prénom/événement/date)"):
        st.caption(
            "Même personne visiblement inscrite plusieurs fois (casse/espaces ignorés). "
            "Supprimez les lignes en trop directement dans le tableau ci-dessus si besoin."
        )
        for position in duplicate_rows:
            r = normalized.iloc[position - 1]
            st.write(f"- Ligne {position} : {r['Nom']} {r['Prénom']}, {r['Événement']}")

if unknown_type_rows:
    with st.expander(f"{len(unknown_type_rows)} type(s) de certificat inconnu(s)"):
        for position in unknown_type_rows:
            r = normalized.iloc[position - 1]
            st.write(f"- Ligne {position} : {r['Nom']} {r['Prénom']}, type \"{r['Type']}\"")

card_end()

# --- Étape 4 : génération ---------------------------------------------------

card_start("4. Génération")


def _rows_to_payload(rows_df: pd.DataFrame) -> list[dict]:
    return [
        {
            "name": r["Nom"],
            "first_name": r["Prénom"],
            "event_name": r["Événement"],
            "event_date": r["Date"],
            "cert_type": r["Type"],
            "email": r["Email"],
        }
        for _, r in rows_df.iterrows()
    ]


def _run_batch_generation(rows_df: pd.DataFrame, send_email: bool) -> None:
    progress = st.progress(30, text="Génération en cours côté serveur...")
    try:
        response = api_request(
            "POST",
            "/api/certificates/batch-rows",
            token=auth["token"],
            json={"rows": _rows_to_payload(rows_df), "send_email": send_email},
        )
        progress.progress(100, text="Terminé.")
        st.session_state["oc_batch_result"] = response.json()
    except ApiError as exc:
        progress.empty()
        st.markdown(badge("error", f"Échec de la génération : {exc.message}"), unsafe_allow_html=True)


send_email = st.checkbox("Envoyer par email", value=False)
st.caption("Génère pour les lignes ayant une adresse email renseignée dans la colonne \"Email\".")

col_generate_all, col_generate_selection = st.columns(2)
with col_generate_all:
    generate_clicked = st.button(
        f"Générer les {len(normalized)} lignes", disabled=normalized.empty, width="stretch"
    )
with col_generate_selection:
    generate_selection_clicked = st.button(
        f"Générer la sélection ({selected_count})",
        icon=":material/rocket_launch:",
        disabled=selected_count == 0,
        width="stretch",
    )

if generate_clicked:
    _run_batch_generation(normalized[TEXT_COLUMNS], send_email)
elif generate_selection_clicked:
    _run_batch_generation(normalized[normalized["Sélection"]][TEXT_COLUMNS], send_email)

card_end()

# --- Résumé ------------------------------------------------------------

result = st.session_state.get("oc_batch_result")
if result:
    card_start("Résumé")

    summary_html = "".join(
        [
            field_row("Générés", str(result["generated"])),
            field_row("Doublons ignorés", str(result["duplicates"])),
            field_row("Erreurs", str(len(result["errors"]))),
            field_row("Emails envoyés", str(result.get("emails_sent", 0))),
        ]
    )
    st.markdown(summary_html, unsafe_allow_html=True)

    if result["errors"]:
        with st.expander(f"Détail des {len(result['errors'])} erreur(s)"):
            st.caption("Le numéro de ligne correspond à la position dans le tableau ci-dessus.")
            for err in result["errors"]:
                st.markdown(
                    badge("error", f"Ligne {err['row']} : {err['error']}"), unsafe_allow_html=True
                )

    if result.get("zip_url"):
        try:
            zip_response = api_request("GET", result["zip_url"], token=auth["token"])
            st.download_button(
                "Télécharger le ZIP",
                icon=":material/download:",
                data=zip_response.content,
                file_name="certificats.zip",
                mime="application/zip",
            )
        except ApiError as exc:
            st.markdown(
                badge("error", f"Impossible de récupérer l'archive : {exc.message}"),
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            badge("warning", "Aucun certificat n'a pu être généré : pas d'archive à télécharger."),
            unsafe_allow_html=True,
        )

    card_end()
