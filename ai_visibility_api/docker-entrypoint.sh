#!/bin/sh
set -e

echo "Applying database migrations..."
flask db upgrade

exec "$@"
