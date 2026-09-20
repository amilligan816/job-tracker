# Job Tracker

A job search assistant: track applications through a pipeline, keep resumes and
job descriptions in object storage, capture postings from a URL or a paste, and
use Claude for match analysis, cover letters and interview prep.

- **Backend** — FastAPI, SQLAlchemy 2 (async) + Postgres, Alembic, MinIO via boto3, Anthropic SDK
- **Frontend** — React + TypeScript + MUI, Vite, TanStack Query, React Router
- **Infra** — Postgres and MinIO in `infra/`, pulled into the root compose file

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| Backend (OpenAPI docs at `/docs`) | http://localhost:8000 |
| MinIO console | http://localhost:9003 |
| Postgres | `localhost:5433` |

Host ports are shifted off the usual defaults so this stack can run alongside
other local projects. Change them in `.env`.

The backend applies migrations on start, and `minio-init` creates the bucket, so
a fresh `docker compose up` gives you a working stack with no extra steps.

## Enabling the assistant

The app runs fully without an API key — the assistant routes return 503 and the
UI shows a notice instead. To turn the features on:

```bash
# in .env
ANTHROPIC_API_KEY=sk-ant-...
```

Then `docker compose up -d --build backend`. This unlocks:

- **Posting extraction** — turns a pasted or fetched posting into structured
  fields (title, company, location, salary, requirements, tech stack)
- **Match analysis** — scores a resume against a posting and names the gaps
- **Cover letter** and **interview prep** drafts, grounded in the stored resume

Runs are persisted in `assistant_runs` with their token usage, so you can see
what was generated and what it cost.

## Layout

```
backend/          FastAPI service
  app/
    models.py     SQLAlchemy tables
    schemas.py    Pydantic request/response models
    storage.py    MinIO object storage
    llm.py        Claude integration
    textextract.py  PDF/HTML -> text
    routers/      companies, postings, applications, documents, assistant
  alembic/        migrations
frontend/         Vite + React + MUI SPA
infra/            Postgres + MinIO compose file
docker-compose.yml  full stack (includes infra/)
```

## Working on it

Storage only, with the app run on the host:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d
```

`--env-file` matters: compose otherwise resolves `.env` next to the compose file
and silently falls back to the built-in defaults.

Backend on the host:

```bash
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
```

Frontend on the host:

```bash
cd frontend && npm install && npm run dev
```

After changing `backend/app/models.py`:

```bash
cd backend && uv run alembic revision --autogenerate -m "describe the change"
```

## Storage notes

Presigned download URLs are signed against `S3_PUBLIC_ENDPOINT_URL`, not the
in-network `S3_ENDPOINT_URL` — the browser resolves those URLs, not the backend.
If downloads 403 or fail to resolve, that pair is the first thing to check.
