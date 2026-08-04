#!/bin/sh
set -eu
mkdir -p /app/storage/imports /app/storage/templates /app/storage/generated
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
