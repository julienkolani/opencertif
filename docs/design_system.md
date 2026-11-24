# OpenCertif : Design System

> Style inspiré Canva : clean, card-based, moderne, aéré.
> Thème neutre par défaut, customisable par instance via variables CSS.
> Pas d'emojis. Utiliser les icônes Material natives de Streamlit
> (`:material/icon_name:`) ou des éléments HTML/CSS.

---

## 1. Principes

- **Aéré** : beaucoup de blanc (ou fond très clair), espacement généreux
- **Card-based** : chaque section/fonctionnalité dans une carte avec ombre subtile et coins arrondis
- **Friendly** : typo arrondie, boutons doux, micro-interactions simples
- **Neutre par défaut** : l'accent color est une variable, chaque instance la remplace
- **Pas de look Streamlit** : on override le thème par défaut via `.streamlit/config.toml` + CSS custom injecté via `st.markdown(unsafe_allow_html=True)`
- **Pas d'emojis** : tous les indicateurs visuels sont des icônes Material natives Streamlit (`:material/icon_name:`) ou des éléments CSS (cercles colorés, bordures, backgrounds)

---

## 2. Palette : variables CSS

```css
:root {
  /* Fond */
  --oc-bg-primary: #FFFFFF;
  --oc-bg-secondary: #F8F9FA;
  --oc-bg-card: #FFFFFF;

  /* Texte */
  --oc-text-primary: #1A1A2E;
  --oc-text-secondary: #6B7280;
  --oc-text-muted: #9CA3AF;

  /* Accent : à remplacer par instance */
  --oc-accent: #7C3AED;
  --oc-accent-hover: #6D28D9;
  --oc-accent-light: #EDE9FE;

  /* Statuts */
  --oc-success: #10B981;
  --oc-success-light: #D1FAE5;
  --oc-error: #EF4444;
  --oc-error-light: #FEE2E2;
  --oc-warning: #F59E0B;
  --oc-warning-light: #FEF3C7;

  /* Bordures & ombres */
  --oc-border: #E5E7EB;
  --oc-border-radius: 12px;
  --oc-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --oc-shadow-md: 0 4px 6px rgba(0, 0, 0, 0.07);
  --oc-shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
}
```

Pour customiser une instance (ex: IndabaX Togo en vert) :
```css
:root {
  --oc-accent: #1B5E3B;
  --oc-accent-hover: #145230;
  --oc-accent-light: #E8F5E9;
}
```

---

## 3. Typographie

| Usage | Police | Taille | Poids |
|---|---|---|---|
| Titres de page | Inter ou DM Sans | 28px | 700 |
| Titres de carte | Inter ou DM Sans | 18px | 600 |
| Corps | Inter | 14px | 400 |
| Labels/captions | Inter | 12px | 500 |
| Boutons | Inter | 14px | 600 |

Fallback : `system-ui, -apple-system, sans-serif`

Import via Google Fonts dans le CSS injecté :
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
```

---

## 4. Iconographie

Librairie : **Material Symbols**, natifs à Streamlit via la syntaxe
`:material/icon_name:`, pas de SVG maison, pas de fichier `icons.py`.
Supportée directement par `st.button`, `st.download_button`,
`st.page_link` (paramètre `icon=`) et par `st.markdown`/`st.write` (comme
texte, ex. `st.markdown(":material/upload:")`).

**Piège à connaître** : la substitution `:material/xxx:` n'a lieu que dans
du texte markdown *réel*. Elle ne fonctionne **pas** à l'intérieur d'une
chaîne HTML injectée via `st.markdown(html, unsafe_allow_html=True)`
(confirmé dans le bundle frontend de Streamlit : la substitution passe par
un plugin remark sur les nœuds texte de l'AST markdown, tandis que le HTML
brut est traité séparément par `rehype-raw` et ne voit jamais ce texte).
Si une icône doit voisiner du HTML custom (ex. la zone d'upload, le bloc
utilisateur de la sidebar), il faut un appel `st.markdown(":material/x:")`
séparé, voir `front/components.py::upload_zone()` pour un exemple.

Icônes utilisées dans le projet :

| Usage | Icône Material | Contexte |
|---|---|---|
| Succès / authentique | Aucune (pastille CSS `.oc-dot-success`) | Badge vérification OK |
| Erreur / altéré | Aucune (pastille CSS `.oc-dot-error`) | Badge vérification KO |
| Avertissement / doublon | Aucune (pastille CSS `.oc-dot-warning`) | Badge doublon ou champ manquant |
| Télécharger | `:material/download:` | Bouton téléchargement PDF/ZIP |
| Upload fichier | `:material/upload:` | Zone drag-and-drop batch |
| Recherche | `:material/search:` | Navigation "Vérifier" |
| Utilisateur | `:material/person:` | Sidebar, infos user connecté |
| Déconnexion | `:material/logout:` | Bouton logout sidebar |
| Réglages | `:material/tune:` | Navigation "Positions" |
| Liste/historique | `:material/list:` | Navigation "Historique" |
| Génération | `:material/add_circle:` | Navigation "Générer" |
| Batch | `:material/layers:` | Navigation "Batch" |

Les badges de statut (succès/erreur/avertissement) n'ont plus d'icône du
tout : une simple pastille CSS colorée (`.oc-dot`) suffit et évite le piège
`unsafe_allow_html` ci-dessus, voir `front/components.py::badge()`.

Intégration en Streamlit :

```python
# Widget natif : passer l'icône en paramètre
st.button("Télécharger", icon=":material/download:")
st.page_link(page, label="Historique", icon=":material/list:")

# Texte markdown autonome (PAS dans du unsafe_allow_html)
st.markdown(":material/upload:")
```

---

## 5. Composants

### Cartes
```
+----------------------------------------+
|                                        |  padding: 24px
|   Titre de section                     |  border-radius: 12px
|   -----------                          |  border: 1px solid var(--oc-border)
|                                        |  box-shadow: var(--oc-shadow-sm)
|   Contenu                              |  background: var(--oc-bg-card)
|                                        |
+----------------------------------------+
```

### Boutons

- **Primaire** : fond `--oc-accent`, texte blanc, border-radius 8px, padding 10px 20px
- **Secondaire** : fond transparent, bordure `--oc-accent`, texte `--oc-accent`
- **Ghost** : pas de bordure, texte `--oc-text-secondary`, hover fond `--oc-bg-secondary`
- **Avec icône** : `st.button(..., icon=":material/x:")`, géré nativement par Streamlit, pas de markup custom

### Champs de formulaire

- Border-radius : 8px
- Bordure : 1px solid `--oc-border`
- Focus : bordure `--oc-accent`, ombre `0 0 0 3px var(--oc-accent-light)`
- Padding : 10px 14px

### Badges / statuts

Pas d'emojis, pas d'icône : juste une pastille CSS colorée devant le texte
(voir aussi `.oc-dot` en section "Tableau (historique)" ci-dessous, même
principe). Structure HTML :

```html
<!-- Succès -->
<span class="oc-badge oc-badge-success">
  <span class="oc-dot oc-dot-success"></span>
  Certificat authentique
</span>

<!-- Erreur -->
<span class="oc-badge oc-badge-error">
  <span class="oc-dot oc-dot-error"></span>
  Fichier altéré ou inconnu
</span>

<!-- Avertissement -->
<span class="oc-badge oc-badge-warning">
  <span class="oc-dot oc-dot-warning"></span>
  Doublon détecté
</span>
```

CSS :
```css
.oc-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
}

.oc-badge-success {
  background: var(--oc-success-light);
  color: var(--oc-success);
}

.oc-badge-error {
  background: var(--oc-error-light);
  color: var(--oc-error);
}

.oc-badge-warning {
  background: var(--oc-warning-light);
  color: var(--oc-warning);
}
```

### Tableau (historique)

- Header : fond `--oc-bg-secondary`, texte `--oc-text-secondary`, uppercase, 12px, font-weight 600
- Lignes : bordure bottom `--oc-border`, hover fond `--oc-bg-secondary`
- Actions par ligne : bouton ghost avec `icon=":material/download:"`
- Pagination : boutons ghost, texte "Page 1 / 12"

### Zone d'upload

Pas d'emoji dossier. L'icône `:material/upload:` doit être son propre
`st.markdown()` (pas de `unsafe_allow_html`, voir section 4), donc la boîte
elle-même est un `st.container(key="oc-upload-zone")` stylé en CSS plutôt
qu'un seul bloc HTML :

```python
with st.container(key="oc-upload-zone"):
    st.markdown(":material/upload:")
    st.markdown(
        '<p class="oc-upload-title">Glissez votre fichier Excel ici</p>'
        '<p class="oc-upload-subtitle">ou cliquez pour parcourir</p>',
        unsafe_allow_html=True,
    )
```

```css
/* Streamlit préfixe la classe du conteneur clé avec "st-key-" */
.st-key-oc-upload-zone {
  border: 2px dashed var(--oc-border);
  border-radius: 12px;
  padding: 40px;
  text-align: center;
  background: var(--oc-bg-secondary);
  transition: border-color 0.2s;
}

.st-key-oc-upload-zone:hover {
  border-color: var(--oc-accent);
}

.st-key-oc-upload-zone [data-testid="stIconMaterial"] {
  color: var(--oc-text-muted);
  font-size: 40px;
  margin-bottom: 12px;
}

.oc-upload-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--oc-text-primary);
}

.oc-upload-subtitle {
  font-size: 13px;
  color: var(--oc-text-muted);
}
```

---

## 6. Layout des pages

### Structure globale
```
+------------------------------------------------------+
|  SIDEBAR                    |  CONTENU PRINCIPAL     |
|                             |                        |
|  Logo / Nom app             |  Titre de page         |
|  -----------                |  -----------           |
|  Navigation                 |                        |
|  [icon] Generer             |  [ Carte 1 ]           |
|  [icon] Batch               |                        |
|  [icon] Historique          |  [ Carte 2 ]           |
|  [icon] Positions           |                        |
|                             |                        |
|  -----------                |                        |
|  [icon] Utilisateur         |                        |
|  Role : admin               |                        |
|  [icon] Deconnexion         |                        |
+------------------------------------------------------+
```

### Page de verification (publique)
```
+------------------------------------------------------+
|              OpenCertif                               |
|              ---------                                |
|                                                       |
|    +-----------------------------------------+        |
|    |  Verifier un certificat                  |        |
|    |                                          |        |
|    |  [Tab: Par code]  [Tab: Par fichier]     |        |
|    |                                          |        |
|    |  +----------------------------------+    |        |
|    |  |  Entrez le code du certificat    |    |        |
|    |  +----------------------------------+    |        |
|    |           [Verifier]                     |        |
|    |                                          |        |
|    +-----------------------------------------+        |
|                                                       |
|    +-----------------------------------------+        |
|    |  [icon:check-circle] Certificat          |        |
|    |  authentique                              |        |
|    |                                          |        |
|    |  Nom       KOLANI Julien                 |        |
|    |  Evenement IndabaX Togo 2026             |        |
|    |  Date      2026-08-25                    |        |
|    |  Type      participation                 |        |
|    |  Emis le   2026-09-01                    |        |
|    +-----------------------------------------+        |
+------------------------------------------------------+
```

### Page batch
```
+------------------------------------------------------+
|  Generation batch                                     |
|                                                       |
|  +-------------------------------------------+       |
|  |  [icon:upload 40px]                        |       |
|  |  Glissez votre fichier Excel ici           |       |
|  |  ou cliquez pour parcourir                 |       |
|  +-------------------------------------------+       |
|                                                       |
|  +-------------------------------------------+       |
|  |  Mapping des colonnes                      |       |
|  |                                            |       |
|  |  Nom       ->  [dropdown: colonnes]        |       |
|  |  Prenom    ->  [dropdown: colonnes]        |       |
|  |  Email     ->  [dropdown: colonnes]        |       |
|  |  Type      ->  [dropdown] ou [appliquer a  |       |
|  |               toutes les lignes: ___]      |       |
|  +-------------------------------------------+       |
|                                                       |
|  +-------------------------------------------+       |
|  |  Apercu (148 lignes)                       |       |
|  |  +------+--------+--------+-------+       |       |
|  |  | Nom  | Prenom | Type   | Statut|       |       |
|  |  +------+--------+--------+-------+       |       |
|  |  | DOE  | John   | org    | [ok]  |       |       |
|  |  | KOSS | Marie  | pres   | [warn]|       |       |
|  |  +------+--------+--------+-------+       |       |
|  +-------------------------------------------+       |
|                                                       |
|  [ ] Envoyer par email    [Generer 146 certificats]  |
+------------------------------------------------------+
```

Les `[ok]`, `[warn]`, `[err]` dans le tableau batch sont des pastilles CSS :
```css
.oc-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.oc-dot-success { background: var(--oc-success); }
.oc-dot-warning { background: var(--oc-warning); }
.oc-dot-error { background: var(--oc-error); }
```

---

## 7. Implémentation Streamlit

### Config thème : `.streamlit/config.toml`
```toml
[theme]
primaryColor = "#7C3AED"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F8F9FA"
textColor = "#1A1A2E"
font = "sans serif"
```

### CSS custom : injecté via `st.markdown()`

Créer un fichier `front/style.css` chargé au démarrage de chaque page :

```python
def load_css():
    css_files = ["style.css"]
    if os.path.exists("custom_theme.css"):
        css_files.append("custom_theme.css")
    for f in css_files:
        with open(f) as fh:
            st.markdown(f"<style>{fh.read()}</style>", unsafe_allow_html=True)
```

Ce fichier override les classes Streamlit par défaut pour coller au design system :
- `.stApp` : fond, typo
- `.stButton > button` : style boutons
- `.stTextInput > div > input` : style champs
- `.stSelectbox` : style dropdowns
- `.stDataFrame` : style tableaux
- `.stTabs` : style onglets
- Sidebar : largeur, fond, espacement

### Cartes custom

Via `st.container(border=True)` (Streamlit >= 1.36) avec CSS override, ou via HTML injecté :

```python
def card_start(title: str = ""):
    html = '<div class="oc-card">'
    if title:
        html += f'<h3 class="oc-card-title">{title}</h3>'
    st.markdown(html, unsafe_allow_html=True)

def card_end():
    st.markdown('</div>', unsafe_allow_html=True)
```

### Icônes dans la navigation sidebar

```python
# Navigation items avec icônes Material natives, passées directement à
# st.page_link(page, label=..., icon=...)
nav_items = [
    (generer_page, ":material/add_circle:"),
    (batch_page, ":material/layers:"),
    (historique_page, ":material/list:"),
    (positions_page, ":material/tune:"),
]
```

---

## 8. Customisation par instance

L'instance override le thème en modifiant :

1. `front/.streamlit/config.toml` : `primaryColor`
2. `front/custom_theme.css` (optionnel, chargé après `style.css`) : override des variables `--oc-accent`, `--oc-accent-hover`, `--oc-accent-light`
3. `front/static/logo.png` (optionnel) : logo affiché dans la sidebar

Le README documente cette procédure en 3 lignes.