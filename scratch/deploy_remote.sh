set -euo pipefail
cd /opt/cafeteria

TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/opt/cafeteria-backups
mkdir -p "$BACKUP_DIR"

echo "=== [1/6] Backup environment and database ==="
if [ -f .env ]; then
  cp .env "$BACKUP_DIR/env-$TS"
  chmod 600 "$BACKUP_DIR/env-$TS"
fi

docker compose exec -T db pg_dump -U cafeteria cafeteria | gzip > "$BACKUP_DIR/db-$TS.sql.gz"
test -s "$BACKUP_DIR/db-$TS.sql.gz"
gzip -t "$BACKUP_DIR/db-$TS.sql.gz"
echo "DB backup verified: $BACKUP_DIR/db-$TS.sql.gz"

echo "=== [2/6] Backup current source ==="
tar --exclude='.venv' --exclude='.git' --exclude='data' --exclude='storage' -czf "$BACKUP_DIR/source-$TS.tar.gz" -C /opt/cafeteria .
echo "Source backup created: $BACKUP_DIR/source-$TS.tar.gz"

echo "=== [3/6] Unpack update package ==="
rm -rf /tmp/cafeteria-update
mkdir -p /tmp/cafeteria-update
unzip -q /tmp/cafeteria-update.zip -d /tmp/cafeteria-update
test -f /tmp/cafeteria-update/docker-compose.yml
test -d /tmp/cafeteria-update/backend

echo "=== [4/6] Sync files to /opt/cafeteria ==="
rsync -a --delete \
  --exclude='.env' \
  --exclude='data/' \
  --exclude='storage/' \
  --exclude='.git/' \
  --exclude='.venv/' \
  /tmp/cafeteria-update/ \
  /opt/cafeteria/

echo "=== [5/6] Build and restart containers ==="
docker compose config -q
docker compose build app
docker compose up -d --remove-orphans app nginx

echo "=== [6/6] Health check and status ==="
sleep 3
docker compose ps
docker compose logs --tail=30 app
rm -f /tmp/cafeteria-update.zip
rm -rf /tmp/cafeteria-update
echo "DEPLOYMENT COMPLETED SUCCESSFULLY!"
