.PHONY: up down logs infra migrate revision fmt test clean

up:            ## Build and start the full stack
	docker compose up --build -d

down:          ## Stop everything
	docker compose down

logs:          ## Tail backend + frontend logs
	docker compose logs -f backend frontend

infra:         ## Start only Postgres + MinIO
	docker compose --env-file .env -f infra/docker-compose.yml up -d

migrate:       ## Apply migrations inside the backend container
	docker compose exec backend alembic upgrade head

revision:      ## Autogenerate a migration: make revision m="add foo"
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

fmt:           ## Lint and format the backend
	cd backend && uv run ruff check --fix . && uv run ruff format .

test:          ## Typecheck the frontend
	cd frontend && npm run lint

clean:         ## Stop and delete volumes (destroys local data)
	docker compose down -v
