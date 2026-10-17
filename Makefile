.PHONY: up down reset logs test ingest health

up:
	docker compose up -d

down:
	docker compose down

reset:
	docker compose down -v
	docker compose up -d
	@echo "Waiting for services to become healthy..."
	@sleep 10
	docker compose exec -T backend python -m backend.load_dataset

logs:
	docker compose logs -f

test:
	python scripts/e2e.py

ingest:
	docker compose exec -T backend python -m backend.load_dataset

health:
	curl -s http://localhost:8000/api/health
