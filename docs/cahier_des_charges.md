# OpenCertif : cahier des charges v2

> Application web open source de génération et vérification de certificats.
> Licence : MIT

---

## 1. Contexte et objectifs

Remplacer le workflow actuel (notebook Colab + Google Drive) par une
application web autonome, modulaire, déployable en Docker, avec :

- Génération unitaire et en batch de certificats PDF
- Vérification publique d'authenticité à deux niveaux (code + intégrité fichier)
- Authentification multi-utilisateurs (Keycloak)
- Architecture découplée API / Front pour faciliter la contribution et la personnalisation

---

## 2. Architecture

```
docker-compose:
  ├── api          (FastAPI, port 8000)   → logique métier, endpoints REST
  ├── front        (Streamlit, port 8501) → client UI, consomme l'API
  ├── keycloak     (port 8080)            → authentification OIDC
  └── keycloak-db  (Postgres)             → stockage Keycloak

Internet
   │
   ▼
[reverse proxy existant : nginx/Caddy]
   ├── certifs.<domaine>  → front:8501
   ├── api.<domaine>      → api:8000
   └── auth.<domaine>     → keycloak:8080
```

**Principes :**

- Le front Streamlit ne touche jamais la DB ni les fichiers directement : tout passe par l'API
- L'API est le produit : documentée (Swagger auto), testable, réutilisable par n'importe quel autre front
- L'auth OIDC se gère côté API (validation du token JWT), Streamlit gère le login/redirect via `st.login()` puis transmet le token dans les headers

---

## 3. Utilisateurs et rôles

| Rôle | Accès |
|---|---|
| **Public** (non authentifié) | Page de vérification uniquement |
| **`certifs-viewer`** (Keycloak) | + historique en lecture seule |
| **`certifs-admin`** (Keycloak) | + génération unitaire, batch, éditeur de positions, téléchargement PDF |

---

## 4. Entrées

### 4.1 Données (fichier Excel pour le batch)

Le fichier uploadé peut être le formulaire d'inscription brut (avec de nombreuses
colonnes non pertinentes). L'application propose un **mapping de colonnes** dans
l'UI : l'admin associe chaque colonne nécessaire à la bonne colonne du fichier.

**Colonnes utiles :**

| Champ | Obligatoire | Notes |
|---|---|---|
| Nom | oui | |
| Prénom | oui | Gestion des noms longs : réduction de taille de police, jamais de troncature |
| Événement | oui | Texte libre, ex: "IndabaX Togo 2026" |
| Date | oui | Date de l'événement |
| Type | oui | Clé correspondant à un type déclaré dans `template_positions.json`. Peut être appliqué en masse depuis l'UI si absent du fichier |
| Email | non | Pour l'envoi optionnel du certificat par email |
| Téléphone | non | Backlog (WhatsApp/SMS), non utilisé en V1 |

### 4.2 Templates PDF

- Un fichier PDF par type de certificat (fond visuel, logos, signatures)
- Déposé manuellement dans `data/templates/`
- Convention de nommage libre, référencé dans `template_positions.json`
- Peut être multi-pages (ex: page 1 = certificat, page 2 = citation)

### 4.3 Définition des templates (`template_positions.json`)

Ce fichier est la **définition complète d'un type de certificat**. Ajouter un
nouveau type = ajouter un template PDF + une entrée ici.

```json
{
  "organisation_2020": {
    "template_file": "Certificat_organisation_2020.pdf",
    "name_position": { "x": 460, "y": 340 },
    "name_font": "Helvetica-Bold",
    "name_max_size": 36,
    "name_min_size": 18,
    "name_max_width": 500,
    "qr_position": { "x": 50, "y": 50 },
    "qr_size": 80,
    "pages": 2,
    "name_page": 1
  }
}
```

### 4.4 Configuration

- `.env` : URLs (BASE_URL publique, Keycloak), chemins de données, config SMTP
- `keycloak/realm-export.json` : realm + rôles + client OIDC pré-configurés

---

## 5. Sorties

### 5.1 PDF générés

Arborescence classée :

```
data/certifs/
  2020/
    organisation/
      {id}_{NOM_Prenom}.pdf
    presentation/
      {id}_{NOM_Prenom}.pdf
  2026/
    participation/
      ...
```

### 5.2 ZIP (batch)

Archive téléchargeable contenant tous les PDF d'un batch.

### 5.3 Base de données SQLite

Un enregistrement par certificat émis.

### 5.4 Vérification publique

- **Niveau 1 (par code)** : QR code / saisie manuelle → affiche les détails ou "introuvable"
- **Niveau 2 (par fichier)** : upload du PDF → comparaison SHA256 → "authentique" ou "altéré/inconnu"

---

## 6. Modèle de données (SQLite)

```sql
CREATE TABLE certificates (
    id              TEXT PRIMARY KEY,       -- secrets.token_hex(16)
    name            TEXT NOT NULL,
    first_name      TEXT NOT NULL,
    event_name      TEXT NOT NULL,
    event_date      TEXT NOT NULL,          -- ISO 'YYYY-MM-DD'
    cert_type       TEXT NOT NULL,          -- clé dans template_positions.json
    generated_at    TEXT NOT NULL,          -- ISO datetime
    generated_by    TEXT,                   -- email/sub Keycloak
    pdf_path        TEXT NOT NULL,
    pdf_checksum    TEXT NOT NULL,          -- SHA256 du fichier PDF final
    email_sent_at   TEXT                    -- ISO datetime, NULL si non envoyé
);

CREATE UNIQUE INDEX idx_dedup
    ON certificates(name, first_name, event_name, event_date);
```

---

## 7. Interfaces (écrans)

### 7.1 Page de vérification publique (`/verifier`)

- **Accès :** tout le monde, sans login
- **Deux modes :**
  - Saisie de code (ou paramètre `?code={id}` via QR) → détails si valide, "introuvable" sinon
  - Upload de PDF → calcul SHA256, comparaison en DB → "authentique" ou "altéré/inconnu"
- **Aucun accès** au reste de l'app (pas de téléchargement, pas de lien vers l'historique)

### 7.2 Génération unitaire (`/generer`)

- **Accès :** `certifs-admin`
- **Formulaire :** nom, prénom, événement, date, type (dropdown depuis les clés de `template_positions.json`)
- **Actions :**
  - Prévisualiser → rendu image sans insertion en DB
  - Générer → crée le PDF, insère en DB, affiche téléchargement + QR
- **Erreur :** doublon détecté → message explicite, pas de génération

### 7.3 Génération batch (`/batch`)

- **Accès :** `certifs-admin`
- **Étapes :**
  1. Upload du fichier Excel
  2. Mapping de colonnes (dropdown par champ nécessaire → colonnes du fichier)
  3. Choix du type (dropdown) si non présent dans le fichier
  4. Aperçu tableau : lignes valides en vert, erreurs en rouge (type inconnu, champs vides, doublons)
  5. Case à cocher "Envoyer par email" (si colonne email mappée)
  6. Confirmation → génération avec barre de progression
  7. Résumé (X générés, Y doublons ignorés, Z erreurs, W emails envoyés) + ZIP téléchargeable

### 7.4 Historique (`/historique`)

- **Accès :** `certifs-admin` + `certifs-viewer`
- **Tableau paginé :** nom, prénom, événement, date, type, généré le, généré par
- **Filtres :** recherche texte (nom/événement), filtre par type, filtre par année
- **Actions (admin) :** re-télécharger le PDF
- **Viewer :** lecture seule, pas de téléchargement

### 7.5 Éditeur de positions (`/positions`)

- **Accès :** `certifs-admin`
- **Fonctionnement :**
  - Dropdown pour choisir le type de template
  - Rendu image du template
  - Champ "nom de test" pré-rempli (nom long pour tester le wrapping)
  - Sliders / saisie numérique : x, y, taille police max/min, largeur max, position QR, taille QR
  - Aperçu live : le nom + QR se superposent sur l'image à chaque changement
  - Bouton Enregistrer → écrit dans `template_positions.json`

### 7.6 Login / Logout

- Géré par Streamlit OIDC natif (`st.login()` / `st.logout()`) → redirige vers Keycloak
- Sidebar : nom utilisateur, rôle, bouton logout

---

## 8. Process : pipeline de génération

### Étape 1 : Validation
- Champs obligatoires non vides
- `type` existe dans `template_positions.json`
- Anti-doublon : `(nom, prénom, événement, date)` unique en DB
- Batch : accumule les erreurs, affiche le rapport avant de lancer

### Étape 2 : Génération de l'identifiant
- `id = secrets.token_hex(16)` (32 caractères hex)
- Vérification unicité en DB

### Étape 3 : Génération du QR code
- Contenu : `https://{BASE_URL}/verifier?code={id}`
- Image PNG en mémoire via `qrcode`
- Position et taille lues depuis `template_positions.json`

### Étape 4 : Overlay sur le template PDF
- Charger le template PDF du type correspondant
- Calculer la taille de police :
  - Partir de `name_max_size`
  - Si `{prénom} {NOM}` dépasse `name_max_width` → réduire jusqu'à `name_min_size`
  - Si toujours trop large → forcer à `name_min_size` (jamais de troncature)
- `reportlab` : overlay transparent avec nom + QR code
- `pypdf` : fusionner sur la page cible
- Pages suivantes (citation, etc.) : copiées telles quelles

### Étape 5 : Écriture du fichier PDF
- Chemin : `data/certifs/{année}/{type}/{id}_{NOM_Prenom}.pdf`
- Création des répertoires si nécessaire

### Étape 6 : Calcul du checksum
- SHA256 du fichier final sur disque

### Étape 7 : Insertion en base
- INSERT avec tous les champs
- Si échec (doublon) → supprimer le PDF, remonter l'erreur

### Étape 7bis : Envoi email (optionnel)
- Si activé ET email renseigné → envoi avec PDF en pièce jointe
- Stocker `email_sent_at` en DB
- Échec d'envoi → log, ne bloque pas la génération, flag "non envoyé"

### Étape 8 : Retour utilisateur
- **Unitaire :** aperçu image + lien téléchargement + QR
- **Batch :** résumé (X OK, Y doublons, Z erreurs, W emails) + ZIP

---

## 9. Process : vérification publique

### Niveau 1 (par code)
1. Recevoir le code (URL `?code=` ou saisie manuelle)
2. `SELECT * FROM certificates WHERE id = ?`
3. Trouvé → afficher nom, prénom, événement, date, type, statut valide
4. Non trouvé → "Certificat introuvable"

### Niveau 2 (par fichier)
1. Recevoir le PDF uploadé
2. Calculer SHA256
3. `SELECT * FROM certificates WHERE pdf_checksum = ?`
4. Match → "Fichier authentique et non altéré" + détails
5. Pas de match → "Fichier non reconnu ou altéré"

---

## 10. Choix techniques

| Domaine | Choix | Pourquoi |
|---|---|---|
| Backend | **FastAPI** (Python) | API REST documentée (Swagger auto), testable, découplée du front |
| Frontend | **Streamlit** (≥ 1.50) | Client rapide à construire, OIDC natif, remplaçable par un front React/Vue demain |
| Auth | **Keycloak** (OIDC) + Postgres | Standard self-hosted, multi-utilisateurs, rôles |
| Base de données métier | **SQLite** | Volume faible (centaines/édition), zéro service supplémentaire |
| Génération PDF | `reportlab` + `pypdf` | Overlay texte + fusion de pages, éprouvé |
| QR code | `qrcode` | Standard, léger |
| Aperçu PDF → image | `pypdfium2` | Pas de dépendance système (vs poppler) |
| Email | SMTP configurable | Simple, compatible avec tout service (Brevo, Mailgun, SMTP perso) |
| Conteneurisation | **Docker + docker-compose** | 4 services : api, front, keycloak, keycloak-db |

---

## 11. Structure du projet

```
opencertif/
├── api/
│   ├── main.py                     # point d'entrée FastAPI
│   ├── routers/
│   │   ├── certificates.py         # endpoints génération unitaire + batch
│   │   ├── verify.py               # endpoints vérification (code + checksum)
│   │   ├── history.py              # endpoint historique (liste, filtres)
│   │   └── templates.py            # endpoint positions (lecture/écriture)
│   ├── core/
│   │   ├── db.py                   # schema + CRUD SQLite
│   │   ├── certgen.py              # overlay nom + QR sur template PDF
│   │   ├── auth.py                 # validation JWT Keycloak, décorateurs de rôle
│   │   ├── config.py               # lecture .env
│   │   └── mailer.py               # envoi email SMTP
│   ├── requirements.txt
│   └── Dockerfile
├── front/
│   ├── app.py                      # point d'entrée Streamlit, navigation
│   ├── pages/
│   │   ├── generer.py
│   │   ├── batch.py
│   │   ├── historique.py
│   │   ├── verifier.py
│   │   ├── templates.py
│   │   └── emails.py
│   ├── requirements.txt
│   └── Dockerfile
├── keycloak/
│   └── realm-export.json           # realm + rôles + client OIDC
├── data/                           # bind-mount, persisté sur le VPS
│   ├── templates/                  # PDF templates (déposés manuellement)
│   ├── certifs/                    # PDF générés (classés année/type/)
│   ├── certificates.db            # SQLite
│   └── template_positions.json    # positions des éléments par type
├── deploy/
│   └── nginx.example.conf
├── docker-compose.yml
├── .env.example
├── LICENSE                         # MIT
└── README.md
```

---

## 12. Endpoints API (résumé)

| Méthode | Route | Auth | Description |
|---|---|---|---|
| POST | `/api/certificates/generate` | admin | Génération unitaire |
| POST | `/api/certificates/batch` | admin | Upload Excel + génération batch |
| GET | `/api/certificates` | admin, viewer | Liste paginée + filtres |
| GET | `/api/certificates/{id}/pdf` | admin | Téléchargement PDF |
| GET | `/api/verify/{code}` | public | Vérification par code |
| POST | `/api/verify/file` | public | Vérification par upload PDF |
| GET | `/api/templates` | admin | Liste des types déclarés |
| GET | `/api/templates/{type}` | admin | Détail positions d'un type |
| PUT | `/api/templates/{type}` | admin | Mise à jour positions |
| GET | `/api/templates/{type}/preview` | admin | Rendu image avec nom de test |

---

## 13. Backlog (hors V1)

- Envoi WhatsApp/SMS (API Business)
- Rôles Keycloak plus fins (par édition/année)
- Upload de templates depuis l'UI
- Multi-langue de l'interface
- Rate-limiting sur la page de vérification
- Export CSV de l'historique
- Front alternatif (React/Vue)

---

## 14. Points à configurer au déploiement

- Sous-domaines : `certifs.<domaine>`, `api.<domaine>`, `auth.<domaine>` (placeholders dans les configs)
- `KC_HOSTNAME=auth.<domaine>` sur Keycloak pour que l'issuer OIDC soit cohérent navigateur/serveur
- Certificats HTTPS (Let's Encrypt via le reverse proxy)
- Config SMTP dans `.env` pour l'envoi d'emails
