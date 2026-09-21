# Job Tracker

A job search assistant: track applications through a pipeline, keep resumes and
job descriptions in object storage, capture postings from a URL or a paste, see
a computed match rating for every role, pick up status changes from your inbox,
and use Claude for deeper analysis, cover letters and interview prep.

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

## Capturing a posting

`POST /api/postings/capture` takes a URL or a pasted description. The raw text is
always stored, so a posting stays re-parseable later.

Most company career pages are a shell around an applicant tracking system: the
HTML served over HTTP is navigation, cookie notices and EEO boilerplate, and the
posting itself is fetched by JavaScript after load. Scraping one of those is
*worse* than fetching nothing — a page of footer text still looks like content,
so the extractor assembles a "posting" out of the legal small print.

So `app/ats.py` goes to the ATS instead, for the three that publish postings over
a public JSON API:

| ATS | URLs it recognises | Endpoint |
| --- | --- | --- |
| Greenhouse | any URL with `gh_jid`, plus `*.greenhouse.io/<org>/jobs/<id>` | per-job |
| Lever | `jobs.lever.co/<site>/<uuid>` | per-job |
| Ashby | `jobs.ashbyhq.com/<org>/<uuid>`, plus any URL with `ashby_jid` | whole board, filtered |

A board is addressed by a short token (`billtrust`) that an embedding page need
not state anywhere machine-readable — Billtrust passes it in `source` and reads
it back in its own inline script. So the resolver collects plausible tokens from
the query string and the hostname and lets the API adjudicate: a wrong guess is a
404, and the first usable answer wins. Anything it cannot resolve falls back to
scraping, which is right for a career page that really does serve HTML.

Two notes on what the APIs give you. Ashby has no per-job endpoint, so its board
is pulled and filtered by id under a size ceiling. Neither Lever nor Ashby names
the company anywhere in its payload, so that field is left empty rather than
guessed from the URL token — the description almost always names the company and
the extractor picks it up from there.

When a page cannot be resolved *and* scrapes to boilerplate, the extractor says
so via `is_job_posting` and the capture is refused with a 422 telling you to paste
the description. That field exists because `title` is required: without somewhere
to report "this is not a posting", the model is forced to invent one out of the
page furniture, and a confident wrong record is worse than an error.

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

## Email updates

Connect a Gmail account and the app reads status changes out of your inbox:
rejections, recruiter screens, interview invitations, offers. Nothing moves on
its own — a sync produces **suggestions**, and accepting one is what changes a
status and writes the timeline entry.

Set it up on the **Email** page. You can connect as many mailboxes as you like —
a personal address and a work one are read into the same review queue, and each
syncs and reconnects independently, so one needing attention does not stop the
other.

The Google Cloud steps are in `.env.example`; you need `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET` and a `MAIL_TOKEN_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Scope is `gmail.readonly`. The app reads mail; it cannot send, label, archive or
delete.

### What it stores

Only messages it can tie to something you are tracking. A sync walks headers
first — sender and subject, which is cheap — and most of an inbox is dropped
right there, unread. A message earns a body fetch only if it comes from a
company you have applied to, from a recognised applicant-tracking system, or in
a thread already filed against an application. What survives classification is
stored; everything else is examined in memory and forgotten.

An email that reaches two connected mailboxes is one thing to review, not two.
Gmail gives the same message a different id in each account, so deduplication
keys on the `Message-Id` the *sender* set, which is the same in both.

Disconnecting an account deletes its messages with it, and leaves any other
connected mailbox untouched.

### How an email is read

Two questions, answered separately because they fail differently.

**Which application is this about** — sender domain against the company's
website and the posting link, company name in the display name or subject, the
role title, and thread continuity (a recruiter's fourth reply rarely names the
company, but it is unambiguously about the same job). A wrong answer here is the
expensive kind, so two applications that match almost equally well produce no
suggestion rather than a coin flip.

**What it says happened** — weighted phrases per status. "We've decided to move
forward with other candidates" is a rejection; "we'd love to move forward" is
not. A decisive rejection outranks everything else in the message, because
rejections routinely thank you for interviewing and mention the offer they are
not making.

Suggestions that would move an application backwards are dropped — an ATS
autoresponder arriving after a phone screen does not un-screen you — and a
closed application is not reopened.

With a Claude credential set, emails the phrases are unsure about get a second
opinion (`MAIL_USE_CLAUDE=false` turns that off). Claude picks from a shortlist
by index rather than naming an application id, so it cannot invent one. Without
a credential the heuristics run alone and the feature still works.

### Syncing

The backend polls every `MAIL_SYNC_INTERVAL_SECONDS` (default 900; `0` disables
the loop and leaves the *Sync now* button). Polling rather than Gmail push
notifications, which need a Pub/Sub topic and a publicly reachable endpoint that
a locally-run stack does not have.

The first sync of a mailbox backfills `MAIL_LOOKBACK_DAYS` (default 30); after
that it resumes from Gmail's history cursor. A run is capped at
`MAIL_MAX_MESSAGES_PER_SYNC`, and a capped run holds its cursor back so the
remainder is picked up next time rather than skipped.

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
    crypto.py     encrypts stored OAuth tokens
    mail/         email sync
      provider.py the interface a mailbox has to present
      gmail.py    Google OAuth + the Gmail API
      classify.py which application an email is about, and what it says
      sync.py     one pass over a mailbox
    render.py     .docx / .pdf rendering
    llm.py        Claude integration
    textextract.py  PDF/HTML -> text
    routers/      companies, postings, applications, documents, assistant, mail
  alembic/        migrations
  tests/          matcher, renderer, experience and mail-classifier tests
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

**Connecting Gmail fails with a redirect URI mismatch.** `GOOGLE_REDIRECT_URI`
has to match what is registered on the OAuth client character for character,
including the scheme and port.

**Google did not issue a refresh token.** This happens when the account has
already granted the app access, so the consent screen is skipped. Remove the app
at https://myaccount.google.com/permissions and connect again.

**A mailbox says it needs reconnecting.** Either the grant was revoked, or
`MAIL_TOKEN_KEY` changed since the tokens were stored — the stored ciphertext
will not decrypt under a new key. Reconnect the account. Other connected
mailboxes keep working; a failed sync is recorded per account.

**Connecting a second mailbox reconnects the first instead.** Google reuses
whichever account the browser is already signed into. Pick the other one on the
account chooser, or sign out of Google first. Accounts are keyed by address, so
re-consenting as the same address updates that account rather than adding one.

## Storage notes

Presigned download URLs are signed against `S3_PUBLIC_ENDPOINT_URL`, not the
in-network `S3_ENDPOINT_URL` — the browser resolves those URLs, not the backend.
If downloads 403 or fail to resolve, that pair is the first thing to check.
