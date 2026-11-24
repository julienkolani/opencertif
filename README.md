# OpenCertif

Application web open source de génération et vérification de certificats
(participation, organisation, présentation...) pour des événements
(conférences, formations, hackathons...). Génération unitaire ou en batch
depuis un fichier Excel, vérification publique par code ou par upload de
fichier, historique, authentification multi-utilisateurs via Keycloak.

Architecture découplée : une API REST ([FastAPI](https://fastapi.tiangolo.com/))
qui porte toute la logique métier, et un client web ([Streamlit](https://streamlit.io/))
qui la consomme. Voir [docs/cahier_des_charges.md](docs/cahier_des_charges.md)
pour la spécification complète et [docs/design_system.md](docs/design_system.md)
pour le design system du front.

---

## Prérequis

- [Docker](https://docs.docker.com/get-docker/) et le plugin
  [Docker Compose](https://docs.docker.com/compose/) (`docker compose version`)
- Python 3.12+ uniquement si vous voulez lancer l'API ou le front hors
  Docker (développement, tests)
- Pour un déploiement en production : un serveur (VM) joignable depuis
  internet, un nom de domaine, et trois sous-domaines pointés dessus
  (`certifs.`, `api.`, `auth.`), voir "Déploiement en production" plus bas

---

## Démarrage local (développement)

```bash
git clone <url-du-repo> opencertif
cd opencertif

cp .env.example .env
# .env par défaut fonctionne tel quel en local (tout sur localhost).

cp front/.streamlit/secrets.toml.example front/.streamlit/secrets.toml
# Éditez ce fichier (voir "Configurer Keycloak" ci-dessous pour récupérer
# client_secret). Sans lui, la connexion admin/viewer ne fonctionne pas :
# seule la page publique /verifier reste utilisable.
# Ce fichier n'est jamais copié dans l'image (front/.dockerignore) : il est
# monté en lecture seule dans le conteneur par docker-compose.yml.

docker compose up -d --build
```

Pour développer le front avec rechargement à chaud (le code de `front/` est
monté dans le conteneur au lieu d'être figé dans l'image), ajoutez le
fichier de dev. **Jamais sur un serveur** :

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Au premier démarrage, Docker construit les images `api` et `front`, télécharge
Keycloak et Postgres, puis importe automatiquement le realm `opencertif`
(rôles + client déjà déclarés dans `keycloak/realm-export.json`). Suivez les
healthchecks avec :

```bash
docker compose ps
```

Une fois les 4 services `healthy` :

- Front : http://localhost:8501
- API (doc Swagger) : http://localhost:8008/docs
- Keycloak (admin console) : http://localhost:8080

> Pour développer sans configurer Keycloak ni `secrets.toml` tout de suite,
> passez `DEV_MODE=true` dans `.env` : l'API contourne l'authentification et
> injecte un faux utilisateur admin (**ne jamais activer en production**).

> `data/templates/` est vide par défaut : `data/template_positions.json`
> référence deux types d'exemple (`participation`, `organisation_2020`)
> dont **les PDF ne sont pas fournis**. Déposez au moins un vrai template
> avant de générer un certificat, voir "Ajouter un nouveau type de
> template" plus bas.

---

## Configurer Keycloak

Ces étapes s'appliquent aussi bien en local (`localhost:8080`) qu'en
production (`https://auth.DOMAIN`, voir la section suivante pour
l'installation complète).

1. Ouvrez la console d'administration et connectez-vous avec les
   identifiants `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` définis dans
   `.env` (`admin` / `admin` par défaut, **à changer avant toute mise en
   ligne**, voir plus bas).
2. En haut à gauche, basculez du realm `master` vers le realm **opencertif**
   (déjà importé automatiquement, avec les rôles `certifs-admin` et
   `certifs-viewer` et le client `opencertif-app`).
3. **Récupérez le secret du client** : *Clients* → `opencertif-app` →
   onglet *Credentials* → *Regenerate*, puis reportez la **même valeur**
   dans `KEYCLOAK_CLIENT_SECRET` (`.env`, utilisé par l'API) **et**
   `client_secret` (`front/.streamlit/secrets.toml`, utilisé par le front
   pour `st.login()`), puis recréez les conteneurs (`docker compose up -d api
   front` : un simple `restart` ne relit pas le `.env`). Le secret livré dans `realm-export.json`
   (`CHANGE_ME_IN_PRODUCTION`) est un placeholder, pas un secret utilisable
   tel quel.
4. **Créez vos utilisateurs** : *Users* → *Add user* (l'auto-inscription
   est désactivée). Onglet *Credentials* pour définir un mot de passe.
5. **Assignez les rôles** : sur la fiche de l'utilisateur, onglet
   *Role mapping* → *Assign role* → `certifs-admin` (accès complet :
   génération, batch, historique, modèles, emails) ou `certifs-viewer`
   (historique en lecture seule).
6. Mettez à jour les *Redirect URIs* et *Web origins* du client
   `opencertif-app` (onglet *Settings*) pour remplacer
   `https://certifs.DOMAIN` par votre domaine réel.
7. **Durée de vie des sessions** (*Realm settings* → onglet *Sessions* et
   *Tokens*) : par défaut, Keycloak émet des jetons d'accès valables
   **5 minutes** (`Access Token Lifespan`), ce qui expire vite pendant une
   utilisation active (l'app redirige alors vers l'écran de connexion,
   voir `utils.py`, `_handle_expired_session`). Cette instance est réglée
   sur **30 minutes**, un compromis raisonnable pour un usage admin ; à
   ajuster selon vos contraintes de sécurité. Deux autres réglages
   comptent : `SSO Session Idle` (déconnexion après inactivité, 30 min par
   défaut) et `SSO Session Max` (durée absolue d'une session, 10h par
   défaut).

### Admin bloqué sur la page « Vérifier »

Symptôme : la connexion Keycloak réussit, mais l'utilisateur ne voit que
la page publique **Vérifier**, même avec le rôle `certifs-admin`.

Deux causes, toutes deux corrigées dans le dépôt, rien à faire sur un
nouveau serveur :

1. **Token non exposé.** Sans `expose_tokens = ["access", "id"]` dans
   la section `[auth]` de `front/.streamlit/secrets.toml`, `st.user.tokens`
   est vide. Le front appelle alors l'API sans token, reçoit un 401, croit
   la session expirée et déconnecte l'utilisateur. La ligne est présente
   dans `secrets.toml.example` et `secrets.production.toml` : conservez-la
   (Streamlit 1.50 minimum, voir `front/requirements.txt`).
2. **Rôles absents de l'ID token.** Le front lit les rôles dans `st.user`,
   c'est-à-dire dans l'ID token, alors que Keycloak ne met par défaut
   `realm_access.roles` que dans l'access token. L'app recevait donc
   `roles = []` et masquait les pages protégées.

Correctifs en place pour la cause 2 :

- `keycloak/realm-export.json` déclare sur le client `opencertif-app` un
  mapper `realm-roles-in-id-token` (type *User Realm Role*, claim
  `realm_access.roles`, *Add to ID token* activé).
- `front/app.py` lit les rôles dans l'access token si l'ID token n'en
  contient pas.

Grâce à ce repli dans `front/app.py`, le mapper n'est plus indispensable.
Il reste utile si un autre client lit l'ID token. Keycloak n'importe
`realm-export.json` qu'au premier démarrage (realm absent de la base) :
sur une base Keycloak restaurée, le mapper peut manquer, sans conséquence
pour OpenCertif.

Si le problème réapparaît : vérifiez `expose_tokens` dans
`front/.streamlit/secrets.toml` (monté dans le conteneur, voir ci-dessous),
puis `docker compose restart front`, et déconnectez-vous puis
reconnectez-vous : un token déjà émis ne change pas.

### « Authentification non configurée sur cette instance »

Le front ne trouve pas `secrets.toml`. Ce fichier n'est **jamais** copié
dans l'image (`front/.dockerignore` l'exclut, pour ne pas embarquer de
secrets) : `docker-compose.yml` le monte en lecture seule depuis
`front/.streamlit/secrets.toml`. Vérifiez que ce fichier existe sur l'hôte
et contient une section `[auth]` complète (copie de
`secrets.toml.example` ou `secrets.production.toml`), puis
`docker compose up -d front`. S'il manquait au démarrage, Docker a pu créer
un **dossier** vide à sa place : supprimez-le avant de recréer le fichier.

---

## Mise en production pas à pas

La procédure complète, dans l'ordre, sur un serveur neuf. Chaque étape
renvoie au détail de la section "Déploiement en production" plus bas.
Dans les commandes, remplacez `exemple.fr` par votre domaine.

### Depuis votre poste

1. **Vérifiez qu'aucun secret n'est versionné.** `git status` ne doit lister
   ni `.env`, ni `.env.production`, ni `front/.streamlit/secrets*.toml`, ni
   `data/certificates.db`. Le `.gitignore` les exclut déjà. Le secret client
   de `keycloak/realm-export.json` doit rester le placeholder
   `CHANGE_ME_IN_PRODUCTION`.
2. **Mettez de côté les fichiers absents du dépôt.** Ils devront être
   copiés à la main sur le serveur :
   - `.env.production`, qui deviendra `.env` (sinon, partez de `.env.example`) ;
   - `front/.streamlit/secrets.production.toml`, qui deviendra
     `secrets.toml` (sinon, partez de `secrets.toml.example`) ;
   - vos templates PDF (`data/templates/*.pdf`). Leur configuration,
     `data/template_positions.json`, est versionnée.

### Préparer le serveur

3. **La machine.** Une VM Linux avec Docker, Docker Compose, nginx et
   certbot. Dans le pare-feu, n'ouvrez que les ports 22, 80 et 443.
4. **Le DNS.** Trois enregistrements A vers l'IP du serveur :
   `certifs.exemple.fr` (front), `api.exemple.fr` (API) et
   `auth.exemple.fr` (Keycloak).
5. **Le code et la configuration**, *avant* tout `docker compose up` :

   ```bash
   git clone <url-du-repo> opencertif && cd opencertif

   # Depuis votre poste :
   #   scp .env.production           serveur:opencertif/.env
   #   scp front/.streamlit/secrets.production.toml \
   #                                 serveur:opencertif/front/.streamlit/secrets.toml
   #   scp data/templates/*.pdf      serveur:opencertif/data/templates/

   sed -i 's/DOMAIN/exemple.fr/g' .env front/.streamlit/secrets.toml keycloak/realm-export.json
   ```

   Deux contraintes d'ordre :
   - `front/.streamlit/secrets.toml` doit exister **avant** le premier
     démarrage. Sinon, Docker crée un dossier vide à sa place (voir
     « Authentification non configurée sur cette instance »).
   - `keycloak/realm-export.json` doit contenir le vrai domaine **avant**
     le premier démarrage : Keycloak ne l'importe qu'une seule fois.

   Vérifiez enfin que le `.env` contient `KC_START_MODE=start`,
   `BIND_ADDR=127.0.0.1`, `DEV_MODE=false` et des secrets forts (voir
   étapes 2 et 3 de la section suivante).
6. **Nginx et le HTTPS** (détail : étape 4 de la section suivante) :

   ```bash
   sudo cp deploy/nginx.example.conf /etc/nginx/sites-available/opencertif.conf
   sudo sed -i 's/DOMAIN/exemple.fr/g' /etc/nginx/sites-available/opencertif.conf
   sudo ln -s /etc/nginx/sites-available/opencertif.conf /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d certifs.exemple.fr -d api.exemple.fr -d auth.exemple.fr
   ```

7. **Le démarrage :**

   ```bash
   docker compose up -d --build
   docker compose ps    # 4 services "healthy" ; Keycloak en mode start : 1 à 2 min
   ```

### Configurer Keycloak (`https://auth.exemple.fr`)

8. Connectez-vous avec le compte `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`
   du `.env`, puis passez sur le realm **opencertif**.
9. **Régénérez le secret client** : *Clients* → `opencertif-app` →
   *Credentials* → *Regenerate*. Reportez la valeur dans `.env`
   (`KEYCLOAK_CLIENT_SECRET`) **et** dans `front/.streamlit/secrets.toml`
   (`client_secret`), puis :

   ```bash
   docker compose up -d api front
   ```

   `up -d` (et non `restart`) recrée les conteneurs pour qu'ils relisent
   le `.env`.
10. **Créez votre compte** : *Users* → *Add user*, mot de passe dans
    l'onglet *Credentials*, puis *Role mapping* → *Assign role*, filtre
    *Filter by realm roles* → `certifs-admin`.
11. **Recommandé** : dans le realm `master`, créez un administrateur
    permanent puis supprimez le compte temporaire créé au premier
    démarrage. Keycloak affiche un bandeau d'avertissement tant que ce
    n'est pas fait.

### Vérifier et finaliser

12. **Tests de bout en bout :**
    - connexion sur `https://certifs.exemple.fr` : les pages **Générer**
      et **Batch** apparaissent dans la barre latérale (sinon, voir « Admin
      bloqué sur la page Vérifier ») ;
    - génération d'un certificat, puis scan de son QR code depuis un
      téléphone : la page de vérification publique doit s'ouvrir ;
    - depuis une autre machine, `curl http://<IP-du-serveur>:8080` doit
      **échouer** : les services ne sont joignables qu'à travers nginx.
13. **Emails** : page **Emails** → *Configuration SMTP*, puis « Tester
    l'envoi » (détail : étape 6 de la section suivante).
14. **Sauvegardes** : un cron qui archive `data/` et la base Keycloak
    (`docker exec opencertif-keycloak-db-1 pg_dump -U keycloak keycloak`),
    avec une copie hors du serveur (détail : étape 7).
15. **Mises à jour ultérieures** :

    ```bash
    git pull && docker compose up -d --build
    ```

En cas de problème au démarrage ou à la connexion, commencez par
`docker compose logs keycloak` et `docker compose logs front`. Si l'API ou
le front n'arrivent pas à joindre `https://auth.exemple.fr` depuis leur
conteneur (hébergeur sans *hairpin NAT*), le message d'erreur le dira
explicitement dans ces logs.

---

## Déploiement en production

Cette section détaille chaque point de la procédure ci-dessus. Elle part
du principe que vous installez l'application sur un serveur neuf, sans
rien de préexistant.

### 1. Serveur et domaine

- Une VM (Linux) avec Docker et Docker Compose installés, joignable depuis
  internet sur les ports 80 et 443.
- Un nom de domaine avec trois sous-domaines pointés vers l'IP du
  serveur (enregistrements DNS de type A) :
  - `certifs.DOMAIN` : le front (Streamlit)
  - `api.DOMAIN` : l'API (FastAPI)
  - `auth.DOMAIN` : Keycloak
- Un reverse proxy sur l'hôte (nginx, exemple fourni) pour terminer le
  HTTPS et router chaque sous-domaine vers le bon conteneur. Voir la
  section 4 ci-dessous. L'application elle-même n'écoute qu'en HTTP en
  interne ; c'est le reverse proxy qui apporte le HTTPS.

### 2. Générer des secrets forts

Cette instance est livrée avec des valeurs de développement (mots de passe
`admin`/`admin`, `SECRET_KEY=change-me-in-production`, etc.) qui doivent
**toutes** être remplacées avant d'exposer l'application publiquement.
Générez chaque secret séparément :

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

> Un `.env.production` et un `front/.streamlit/secrets.production.toml`
> pré-remplis avec des secrets déjà générés peuvent exister à la racine du
> projet (jamais commités, voir `.gitignore`) : il ne reste alors qu'à y
> remplacer `DOMAIN` et à compléter `KEYCLOAK_CLIENT_SECRET`/`client_secret`
> après le premier déploiement (étape 2 du tableau ci-dessous), puis à les
> renommer en `.env` / `secrets.toml` sur le serveur de production.

| Secret | Où | Rôle |
|---|---|---|
| `SECRET_KEY` | `.env` | Clé de chiffrement symétrique (Fernet) utilisée pour chiffrer les secrets stockés en base, en pratique le mot de passe SMTP saisi depuis la page Emails de l'app. Sans cette clé (ou avec la valeur par défaut laissée en place), ce mot de passe est stocké **en clair** dans la base SQLite. Elle ne sert à rien d'autre (pas de session, pas de cookie) : elle sert uniquement au chiffrement au repos de ces quelques champs sensibles en base. |
| `KEYCLOAK_ADMIN_PASSWORD` | `.env` | Mot de passe du compte admin Keycloak (console d'administration). |
| `KEYCLOAK_DB_PASSWORD` | `.env` | Mot de passe de la base Postgres interne de Keycloak (service `keycloak-db`), jamais exposée hors du réseau Docker, mais doit rester un vrai secret. |
| `KEYCLOAK_CLIENT_SECRET` | `.env` + `front/.streamlit/secrets.toml` (`client_secret`) | Secret du client OIDC `opencertif-app`, régénéré depuis la console Keycloak (voir "Configurer Keycloak", étape 3), pas généré à la main. |
| `cookie_secret` | `front/.streamlit/secrets.toml` | Clé de signature du cookie de session Streamlit (`st.login()`/`st.user`). Propre à chaque instance. |

### 3. Configurer `.env` pour la production

Partez de `.env.example` et renseignez au minimum :

```bash
BASE_URL=https://certifs.DOMAIN
API_URL=http://api:8000          # inchangé : nom du service dans le réseau Docker interne

KEYCLOAK_URL=https://auth.DOMAIN
KC_HOSTNAME=auth.DOMAIN
KEYCLOAK_REALM=opencertif
KEYCLOAK_CLIENT_ID=opencertif-app
KEYCLOAK_CLIENT_SECRET=<secret régénéré, voir "Configurer Keycloak">
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=<secret généré>
KEYCLOAK_DB_PASSWORD=<secret généré>

CORS_ORIGINS=https://certifs.DOMAIN

SECRET_KEY=<secret généré>

DEV_MODE=false                   # non négociable en production
KC_START_MODE=start              # Keycloak en mode production
BIND_ADDR=127.0.0.1              # ports joignables uniquement via nginx
```

Toutes ces valeurs (sauf les 4 chemins `DB_PATH`/`TEMPLATES_DIR`/
`CERTIFS_DIR`/`POSITIONS_FILE`, propres au conteneur, et `DEV_MODE`,
verrouillé à `false` par sécurité) sont lues directement depuis `.env` par
`docker-compose.yml` : il n'y a rien d'autre à modifier dans le compose
file lui-même.

Copiez aussi `front/.streamlit/secrets.toml.example` vers
`front/.streamlit/secrets.toml` et renseignez `redirect_uri` (`https://certifs.DOMAIN/oauth2callback`),
`server_metadata_url` (`https://auth.DOMAIN/realms/opencertif/.well-known/openid-configuration`),
`client_id`, `client_secret` et un `cookie_secret` généré (voir étape 2).

### 4. Reverse proxy et HTTPS

Un exemple de configuration nginx est fourni dans
[deploy/nginx.example.conf](deploy/nginx.example.conf) : un bloc `server`
par sous-domaine, routé vers le port local du conteneur correspondant
(front `8501`, API `8008`, Keycloak `8080`).

```bash
sudo cp deploy/nginx.example.conf /etc/nginx/sites-available/opencertif.conf
# Remplacez DOMAIN par votre domaine réel dans les trois blocs.
sudo ln -s /etc/nginx/sites-available/opencertif.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Une fois les DNS propagés et les trois blocs actifs en HTTP :
sudo certbot --nginx -d certifs.DOMAIN -d api.DOMAIN -d auth.DOMAIN
```

`certbot` réécrit automatiquement chaque bloc pour ajouter le HTTPS et la
redirection HTTP → HTTPS. Les commentaires du fichier détaillent les
particularités à connaître (WebSocket pour Streamlit, taille max des
uploads Excel, en-têtes `X-Forwarded-*` nécessaires à Keycloak pour
générer un issuer OIDC cohérent).

Keycloak démarre en mode `start-dev` en local et en mode `start` en
production, selon la variable `KC_START_MODE` du `.env` (déjà réglée sur
`start` dans `.env.production`). Le compose est déjà prêt pour le reverse
proxy : Keycloak parle en HTTP derrière nginx (`KC_HTTP_ENABLED`) et
construit ses URL `https://` à partir des en-têtes `X-Forwarded-*`
(`KC_PROXY_HEADERS=xforwarded`). La version de Keycloak est fixée dans
`docker-compose.yml` : pour la mettre à jour, changez le tag de l'image
après avoir lu les notes de version
([documentation reverse proxy](https://www.keycloak.org/server/reverseproxy)).

### 5. Démarrer

```bash
docker compose up -d --build
docker compose ps   # attendre que les 4 services soient "healthy"
```

Suivez ensuite "Configurer Keycloak" ci-dessus (mêmes étapes qu'en local,
sur `https://auth.DOMAIN`) pour créer les utilisateurs et assigner les
rôles.

### 6. Emails (SMTP)

La configuration SMTP se fait depuis l'UI (page **Emails**, onglet
*Configuration SMTP*) plutôt que dans `.env` : elle est stockée en base
(chiffrée si `SECRET_KEY` est défini, voir étape 2). Avec Gmail :

- Hôte : `smtp.gmail.com`, port `587`, sécurité `starttls`.
- Utilisateur : l'adresse Gmail complète.
- Mot de passe : un **mot de passe d'application** (16 caractères), généré
  sur `myaccount.google.com/apppasswords`, ce qui nécessite la validation en 2
  étapes activée sur le compte. Le mot de passe Gmail habituel ne
  fonctionne pas en SMTP.
- Utilisez le bouton "Tester l'envoi" avant un envoi réel. Gmail plafonne
  à environ 500 emails/jour pour un compte gratuit.

### 7. Sauvegardes

Toutes les données persistantes vivent dans `data/` (bind-mount décrit
dans "Structure du projet" plus bas) : la base SQLite
(`data/certificates.db`), les PDF générés (`data/certifs/`) et les
templates (`data/templates/`). Rien de tout cela n'est répliqué par
défaut : une sauvegarde régulière (cron + copie hors du serveur) est
indispensable avant toute mise en ligne réelle, par exemple :

```bash
tar czf opencertif-backup-$(date +%F).tar.gz data/
```

La base Postgres de Keycloak (volume Docker `keycloak-db-data`) mérite la
même attention si vous ne voulez pas reperdre utilisateurs et rôles en cas
de panne disque (`docker exec opencertif-keycloak-db-1 pg_dump -U keycloak keycloak`).

### 8. Checklist avant mise en ligne

- [ ] Tous les secrets de l'étape 2 générés et renseignés (aucune valeur
      par défaut restante : `admin`/`admin`, `change-me-in-production`,
      `keycloak_password`)
- [ ] `.env` : `BASE_URL`, `KEYCLOAK_URL`, `KC_HOSTNAME`, `CORS_ORIGINS`
      pointent sur les vrais domaines (plus de `localhost`)
- [ ] `.env` : `KC_START_MODE=start` et `BIND_ADDR=127.0.0.1`
      (`curl http://<IP>:8080` depuis l'extérieur doit échouer)
- [ ] `DEV_MODE=false` (déjà verrouillé dans `docker-compose.yml`, à
      vérifier si vous lancez l'API autrement que via ce compose file)
- [ ] `front/.streamlit/secrets.toml` renseigné avec les vraies URLs et un
      `cookie_secret` propre à cette instance
- [ ] Reverse proxy + HTTPS actifs sur les trois sous-domaines
      (certificats valides, pas d'avertissement navigateur)
- [ ] *Redirect URIs* / *Web origins* du client Keycloak mis à jour avec
      le vrai domaine
- [ ] `expose_tokens = ["access", "id"]` présent dans
      `front/.streamlit/secrets.toml`, et connexion admin testée (les pages
      Générer et Batch apparaissent, voir "Admin bloqué sur la page
      « Vérifier »")
- [ ] Au moins un vrai template PDF déposé (`data/templates/`) et
      configuré (`data/template_positions.json`)
- [ ] SMTP configuré et testé depuis la page Emails
- [ ] Sauvegarde automatisée de `data/` et de la base Postgres Keycloak en
      place

---

## Ajouter un nouveau type de template

Un type de certificat = un PDF + une entrée dans `data/template_positions.json`.

1. Déposez le PDF du template dans `data/templates/` (convention de nom
   libre, ex : `Certificat_hackathon_2027.pdf`).
2. Ajoutez une entrée dans `data/template_positions.json` avec une clé de
   votre choix (c'est cette clé qui apparaît comme "type" dans l'app) :

   ```json
   "hackathon_2027": {
     "template_file": "Certificat_hackathon_2027.pdf",
     "name_position": { "x": 421, "y": 300 },
     "name_font": "Helvetica-Bold",
     "name_max_size": 36,
     "name_min_size": 18,
     "name_max_width": 500,
     "qr_position": { "x": 50, "y": 50 },
     "qr_size": 80,
     "pages": 1,
     "name_page": 1
   }
   ```

3. Affinez les positions dans l'app (page **Modèles**, onglet éditeur
   visuel, réservée aux admins) : sélectionnez le nouveau type, ajustez
   les sliders en vous aidant de l'aperçu live, puis *Enregistrer*.

Le type est immédiatement disponible dans les formulaires de génération
unitaire et batch, sans redémarrage nécessaire.

---

## Customiser le thème

Une instance peut se personnaliser (couleur, logo) sans toucher au code,
via 3 fichiers :

1. **`front/.streamlit/config.toml`** : `primaryColor` (thème natif
   Streamlit, utilisé avant même le chargement du CSS custom).
2. **`front/custom_theme.css`** : redéfinit les variables `--oc-accent`,
   `--oc-accent-hover`, `--oc-accent-light` consommées par tout le design
   system (boutons, focus des champs, badges...). Le fichier contient déjà
   un exemple commenté.
3. **`front/static/logo.png`** : logo affiché dans la sidebar (optionnel ;
   sans ce fichier, seul le nom "OpenCertif" est affiché).

Voir [docs/design_system.md](docs/design_system.md), section 8, pour le
détail.

---

## Structure du projet

```
opencertif/
├── api/
│   ├── main.py                     # point d'entrée FastAPI
│   ├── routers/
│   │   ├── certificates.py         # génération unitaire + batch, téléchargement PDF
│   │   ├── verify.py               # vérification publique (code + checksum)
│   │   ├── history.py              # historique paginé + filtres
│   │   ├── templates.py            # lecture/édition de template_positions.json
│   │   └── email.py                # config SMTP + envoi (unitaire, en masse)
│   ├── core/
│   │   ├── db.py                   # schéma + CRUD SQLite
│   │   ├── certgen.py              # overlay nom + QR sur template PDF
│   │   ├── auth.py                 # validation JWT Keycloak, dépendances de rôle
│   │   ├── config.py               # lecture .env (Settings, singleton)
│   │   ├── crypto.py               # chiffrement Fernet des secrets en base (SECRET_KEY)
│   │   ├── mailer.py               # envoi email SMTP
│   │   └── utils.py                # SHA256, normalisation de dates
│   ├── requirements.txt
│   └── Dockerfile
├── front/
│   ├── app.py                      # point d'entrée Streamlit, navigation par rôle
│   ├── pages/
│   │   ├── generer.py
│   │   ├── batch.py
│   │   ├── historique.py
│   │   ├── verifier.py
│   │   ├── templates.py
│   │   └── emails.py
│   ├── utils.py                    # load_css, appels API, session/auth
│   ├── components.py               # cartes, badges, pastilles (design system)
│   ├── icons.py                    # icônes Lucide en SVG inline
│   ├── style.css                   # design system (variables + overrides Streamlit)
│   ├── custom_theme.css            # override d'instance (couleur d'accent)
│   ├── .streamlit/
│   │   ├── config.toml             # thème natif Streamlit
│   │   └── secrets.toml.example    # à copier en secrets.toml (jamais commité)
│   ├── requirements.txt
│   └── Dockerfile
├── keycloak/
│   └── realm-export.json           # realm + rôles + client OIDC pré-configurés
├── data/                           # bind-mount, persisté sur le serveur
│   ├── templates/                  # PDF templates (déposés manuellement)
│   ├── certifs/                    # PDF générés (classés année/type/)
│   ├── certificates.db             # SQLite
│   └── template_positions.json     # positions des éléments par type
├── deploy/
│   └── nginx.example.conf          # reverse proxy + commentaires Let's Encrypt
├── docs/
│   ├── cahier_des_charges.md       # spécification complète
│   └── design_system.md            # design system du front
├── tests/                          # pytest : API (routers, core) + auth
├── docker-compose.yml              # stack complète (prod et local)
├── docker-compose.dev.yml          # dev uniquement : rechargement à chaud du front
├── requirements-dev.txt
├── .env.example
├── .gitignore                      # .env, secrets.toml, data/ runtime, __pycache__...
├── LICENSE                         # MIT
└── README.md
```

---

## Développement / tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

Les tests couvrent la base de données, la génération de PDF/QR, l'auth
JWT, le mailer et l'ensemble des routers API (avec `DEV_MODE` pour
contourner Keycloak). Le front n'a pas de suite de tests committée ; il se
vérifie via `streamlit.testing.v1.AppTest` ou manuellement (`streamlit run
front/app.py`).

---

## Contribution

1. Forkez le dépôt et créez une branche depuis `main`
   (`git checkout -b feat/mon-ajout`).
2. Gardez les changements ciblés : un PR = un sujet. Ajoutez ou mettez à
   jour les tests correspondants (`pytest tests/`) avant de proposer la PR.
3. Suivez le style du code existant (pas de dépendances superflues, pas de
   logique dupliquée entre `api/core/` et `front/`).
4. Ouvrez une pull request en décrivant le problème résolu et la démarche.
   Les PR qui touchent au design front doivent rester cohérentes avec
   [docs/design_system.md](docs/design_system.md).

Les bugs et idées de fonctionnalités se déclarent via les issues du dépôt.

---

## Licence

MIT, voir [LICENSE](LICENSE).
