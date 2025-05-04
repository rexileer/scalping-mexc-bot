#!/bin/sh
# wait-for-db.sh

set -e

host="$1"
shift
cmd="$@"

# Ждем, пока DNS будет доступен
until getent hosts $host > /dev/null 2>&1; do
  >&2 echo "Waiting for DNS resolution of $host..."
  sleep 1
done

# Ждем, пока база данных будет доступна
until PGPASSWORD=$POSTGRES_PASSWORD psql -h "$host" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\q' > /dev/null 2>&1; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 1
done

>&2 echo "Postgres is up - executing command"
exec $cmd 