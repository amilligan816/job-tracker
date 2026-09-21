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

## Experience

There is no stored base resume. The candidate's career lives as structured data
— roles with achievement highlights, deeper stories, and education — and a
resume is *rendered* from it on demand.

Two ways to fill it:

- **Import a resume.** PDF, Word, text or markdown is read, Claude structures
  it, and you review before anything is saved. The file itself is not kept.
  Importing again appends, and skips roles or education already recorded, so
  re-importing the same resume is a no-op rather than a doubled history.
- **Talk it through.** The *Deepen it* tab interviews you about what you
  actually did — scope, constraints, the decision and why, what went wrong.
  When a complete story emerges it is proposed for approval; nothing is saved
  silently.

One plain-text rendering of the record serves both the matcher and the
assistant, so a match score and a cover letter can never disagree about your
history. The *What the model sees* tab shows that exact text.

## Generating a resume

From an application, a resume is built from the record and a template.

- **Untailored** is a straight render — no model call, instant and free.
- **Tailored** asks Claude to select and sharpen the highlights for that
  posting. It references roles by id, so companies, titles and dates always
  come from your record; a role id the model invents is dropped rather than
  rendered. It is told to rephrase, never to add a metric or technology the
  record does not contain.

Output goes to PDF or Word through the same renderer as everything else, and is
filed against the application.

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

The app runs without a Claude credential — those routes return 503 and the UI
says so. Match ratings, untailored resumes and all tracking still work.

To turn the features on, use a **Console API key**, which is the supported way
to authenticate an application:

```bash
# in .env — from https://console.anthropic.com/settings/keys
ANTHROPIC_API_KEY=sk-ant-...
```

A **Claude Pro/Max subscription is not an API credential** and cannot be used
here. It authorizes you to use Claude's own apps, not to act as a backend for
another service, and there is no supported path to point the Messages API at
it. The two are billed separately.

Two other credential sources are honoured if your setup uses them —
`ANTHROPIC_AUTH_TOKEN` for an OAuth access token, and `ANTHROPIC_AMBIENT_AUTH=true`
to let the SDK find an `ant auth login` profile or workload identity on disk.
In Docker the profile has to be mounted in as well:

```yaml
# docker-compose.yml, under the backend service
volumes:
  - ~/.config/anthropic:/root/.config/anthropic:ro
```

### Roughly what it costs

Per application, working it fully (posting extraction, match analysis, a cover
letter, interview prep, a tailored resume) lands around **$0.30–0.50** on
`claude-opus-5` at $5/$25 per MTok. Prompt caching takes a chunk off that,
since the experience record is resent on every call and is cached.
`ANTHROPIC_MODEL` accepts `claude-sonnet-5` or `claude-haiku-4-5` if you want
that lower.

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
    experience.py the career record and its text rendering
    matching.py   deterministic match rating
    skills.py     skill vocabulary (plain data)
    render.py     .docx / .pdf rendering
    llm.py        Claude integration
    textextract.py  PDF/HTML -> text
    routers/      companies, postings, applications, documents, assistant
  alembic/        migrations
  tests/          matcher, renderer and experience tests
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

## Why no vector search

The corpus here is one person's career — on the order of 20–30k tokens fully
written out. That fits in context many times over, so retrieval would solve a
problem this app does not have, and would actively hurt the main job: "which of
my stories fits this posting" is a comparison across everything, and top-k
retrieval answers it by discarding most candidates before the model sees them.

The cost of resending the record is handled by prompt caching instead — it is
stable across a conversation, so it sits behind a cache breakpoint in the
system prompt. Worth revisiting only if the record passes ~100k tokens or this
goes multi-user.

## Troubleshooting

**A frontend edit doesn't show up.** Vite's transform cache in the container can
go stale even though the bind mount has the new file. `docker compose restart
frontend` clears it.

## Storage notes

Presigned download URLs are signed against `S3_PUBLIC_ENDPOINT_URL`, not the
in-network `S3_ENDPOINT_URL` — the browser resolves those URLs, not the backend.
If downloads 403 or fail to resolve, that pair is the first thing to check.
