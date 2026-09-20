# Job Tracker

A job search assistant: track applications through a pipeline, keep resumes and
job descriptions in object storage, capture postings from a URL or a paste, see
a computed match rating for every role, and use Claude for deeper analysis,
cover letters and interview prep.

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

## Resumes

Documents are grouped by what they are for:

- **Base resumes** — your master resumes. One is marked as *the* base (the star
  on the Documents page); it is what tailored resumes are written from and the
  fallback for any application without one.
- **Tailored resumes** — a version written for one application, optionally
  recording which base it came from.
- **Cover letters, portfolios, offer letters, other** — everything else.

When something needs "the resume" for an application it resolves, in order: a
resume you named explicitly, the tailored resume for that application, the
designated base resume, then the most recent base resume.

## Match rating (no AI)

Every application gets a 0-100 rating computed from the posting text and your
resume — no model call, so it is instant, free, and gives the same answer every
time. It shows as a column on the applications list and as a breakdown on the
detail page.

How it works:

- Both sides are scanned against a skill vocabulary (`backend/app/skills.py` —
  plain data, add a row and it is picked up).
- Posting skills are weighted by how firmly they are asked for. Structured
  `requirements` from Claude extraction weigh most; a line that reads like a
  requirement in the raw text weighs more than a passing mention.
- The score is the share of that weight your resume covers, blended with a
  years-of-experience comparison when both sides state one. A signal the
  documents don't carry is dropped rather than counted against you.
- Terms that are also ordinary English (`go`, `c`, `r`) only count when they
  read as a listed technology, so "go to the office" is not a hit for Go.

A null score means there is no resume, or the posting names too few
recognisable skills to rate honestly. Results are cached on the text itself, so
rating a page of applications does not rescan the same posting each time.

Run the tests with `cd backend && uv run pytest`.

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
- **Match analysis** — a narrative read on fit, with gaps and talking points
  (deeper than the computed rating above, which always works)
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
    matching.py   deterministic match rating
    skills.py     skill vocabulary (plain data)
    resumes.py    which resume applies to an application
    llm.py        Claude integration
    textextract.py  PDF/HTML -> text
    routers/      companies, postings, applications, documents, assistant
  alembic/        migrations
  tests/          matcher unit tests
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
