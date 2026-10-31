.PHONY: setup db seed reset api web dev test e2e smoke-meta

setup:
	cd backend && uv sync
	cd frontend && npm install
	@test -f .env || cp .env.example .env

db:
	cd backend && uv run alembic upgrade head

seed: db
	cd backend && uv run python -m app.demo.seed

# Drops every record, including investigations you created, then rebuilds the demo.
reset: db
	cd backend && uv run python -m app.demo.seed --reset

api:
	cd backend && uv run uvicorn app.main:app --port 8000 --reload

web:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 api web

test:
	cd backend && uv run pytest -q

# Needs `make api` and `make web` running. Wipes the demo before and after.
e2e: reset
	cd frontend && npx playwright test
	$(MAKE) reset

# Calls the real Meta Model API once per protocol feature. Needs MODEL_API_KEY and META_MODEL_ID.
smoke-meta:
	cd backend && uv run python -m app.reasoning.smoke
