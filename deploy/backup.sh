#!/usr/bin/env bash
# Sauvegarde complète d'OpenCertif, à lancer depuis n'importe où sur le
# serveur (stack démarrée) ou depuis un cron :
#
#   deploy/backup.sh                  # sauvegarde dans ./backups/
#   deploy/backup.sh /srv/sauvegardes # dossier de destination au choix
#   KEEP_DAYS=30 deploy/backup.sh     # rétention (14 jours par défaut)
#
# Exemple de cron quotidien à 3 h (crontab -e) :
#   0 3 * * * /home/USER/opencertif/deploy/backup.sh >> /home/USER/opencertif-backup.log 2>&1
#
# Contenu de chaque sauvegarde (un dossier horodaté) :
#   certificates.db     base SQLite : certificats, réglages, journal des emails
#   data-files.tar.gz   PDF générés, templates, template_positions.json
#   keycloak.sql.gz     utilisateurs, rôles et configuration Keycloak
#
# La base SQLite est en mode WAL : copier le fichier .db (cp, tar) pendant
# que l'API tourne peut produire une copie incomplète ou corrompue. Ce script
# passe par l'API de sauvegarde de SQLite, cohérente même pendant des
# écritures, puis vérifie l'intégrité de la copie.
#
# Copiez ensuite ces sauvegardes HORS du serveur (rsync, rclone...) : une
# sauvegarde restée sur le même disque ne protège pas d'une panne de ce disque.
set -euo pipefail

cd "$(dirname "$0")/.."
DEST="${1:-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
OUT="$DEST/opencertif-$(date +%F_%H%M%S)"
mkdir -p "$OUT"

echo "Sauvegarde dans $OUT"

# 1. Base SQLite : copie cohérente + contrôle d'intégrité dans le conteneur
#    api, puis rapatriée par la sortie standard (aucun fichier root dans data/).
docker compose exec -T api python - <<'PY' > "$OUT/certificates.db"
import sqlite3, sys
tmp = "/tmp/opencertif-backup.db"
src = sqlite3.connect("/app/data/certificates.db")
dst = sqlite3.connect(tmp)
src.backup(dst)
src.close()
status = dst.execute("PRAGMA integrity_check").fetchone()[0]
dst.close()
if status != "ok":
    sys.exit(f"Copie SQLite invalide : {status}")
with open(tmp, "rb") as f:
    sys.stdout.buffer.write(f.read())
PY
echo "  certificates.db   OK (intégrité vérifiée)"

# 2. Fichiers : tout data/ sauf la base vivante (déjà copiée proprement).
tar czf "$OUT/data-files.tar.gz" --exclude='certificates.db*' data/
echo "  data-files.tar.gz OK"

# 3. Keycloak : dump de sa base Postgres.
docker compose exec -T keycloak-db pg_dump -U keycloak keycloak | gzip > "$OUT/keycloak.sql.gz"
echo "  keycloak.sql.gz   OK"

# 4. Rétention : supprime les sauvegardes de plus de KEEP_DAYS jours.
find "$DEST" -maxdepth 1 -type d -name 'opencertif-*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +

echo "Terminé ($(du -sh "$OUT" | cut -f1))."
