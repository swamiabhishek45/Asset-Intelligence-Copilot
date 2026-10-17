#!/usr/bin/env bash
set -e

CMD=${1:-up}

case "$CMD" in
  up)
    docker compose up -d
    ;;
  down)
    docker compose down
    ;;
  reset)
    docker compose down -v
    docker compose up -d
    echo "Waiting for services to become healthy..."
    sleep 10
    docker compose exec -T backend python -m backend.load_dataset
    ;;
  logs)
    docker compose logs -f
    ;;
  test)
    python scripts/e2e.py
    ;;
  *)
    echo "Usage: $0 {up|down|reset|logs|test}"
    exit 1
    ;;
esac
