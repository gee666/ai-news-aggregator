# News Bot AI

Foundational MVP skeleton for a personal AI news aggregation bot.

## Quick start

The simplest path is the one-shot launcher, which checks Docker, creates `.env`,
builds the images, walks you through pi authentication (copy `auth.json` or
browser login), and starts everything:

```bash
python3 launch.py
```

If Docker is already running and pi is already logged in, it just (re)starts the
stack without prompting.

Manual alternative:

```bash
cp .env.example .env
# edit .env with credentials as needed
docker compose up --build
```

The default compose stack starts PostgreSQL with pgvector, the FastAPI app, worker, bot, and model-init services.

## Local Python dependencies

Do not install dependencies globally. Use a contained environment if running outside Docker:

```bash
python3.14 -m venv .venv
. .venv/bin/activate
pip install -e ".[models,bot,collectors]"
```

## API

FastAPI exposes:

- `GET /health`
- `GET /sources`
- `GET /raw-items`
- `GET /summaries`
- `GET /clusters`
- `GET /search?q=...`
- `POST /submit` with JSON `{"url": "..."}` or `{"text": "..."}`
- `POST /jobs/run-once/{job_name}`

Worker job names:

```text
collect_telegram_channels
collect_gmail_newsletters
collect_rss_sources
process_new_raw_items
fetch_and_parse_links
run_pre_summary_dedup
summarize_ready_items
embed_new_summaries
cluster_new_summaries
generate_or_update_cluster_summaries
send_digest_to_telegram
```

The worker uses APScheduler when installed and falls back to an import-safe asyncio loop otherwise.

## Telegram bot

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_OWNER_CHAT_ID`. The bot is owner-only and supports:

```text
/start
/latest
/digest
/search <query>
/submit <url or text>
/sources
/status
```

The `send_digest_to_telegram` worker job sends `/digest` content to the configured owner.

## Helper commands

OAuth/session initialization helpers:

```bash
docker compose run --rm app python scripts/init_oauth.py gmail
docker compose run --rm app python scripts/init_oauth.py telegram
```

After credentials/sessions are stored in the `secrets` volume, normal startup remains:

```bash
docker compose up --build
```

## LLM via the pi agent

The bot no longer calls any LLM API directly. Every LLM operation
(summarization, metadata extraction, dedup adjudication) shells out to the
local [pi](https://pi.dev) coding agent as a subprocess:

```bash
pi -p "<prompt>"
```

The Docker image installs the latest `@earendil-works/pi-coding-agent` plus the
`oira666_pi-limits-wait` and `oira666_pi-web-search` extensions. Calls run pi
with a minimal tool allowlist — most prompts use `--no-tools` (pure reasoning),
while research prompts can be given `web_search` (to search) and `Bash` (to
fetch links), without exposing read/write/edit tools.

### pi authentication (OAuth)

pi keeps its OAuth credentials in `$PI_CODING_AGENT_DIR/auth.json`
(`/root/.pi/agent/auth.json` in the container, persisted in the `pi_config`
volume). Authenticate using either approach:

1. Copy an existing host `auth.json`. Point `PI_HOST_AUTH_DIR` at a host
   directory containing `auth.json`, then import it:

   ```bash
   # PI_HOST_AUTH_DIR=/home/you/.pi/agent in .env
   docker compose run --rm app python scripts/init_oauth.py pi --import-auth
   ```

2. Log in interactively inside the container:

   ```bash
   docker compose run --rm app python scripts/init_oauth.py pi
   ```

Both options work because the `pi_config` volume persists `auth.json` across
restarts.

Collector, AI, and preprocessing internals are still MVP placeholders, but routes, worker job dispatch, and owner-only bot commands are wired and import-safe for optional bot dependencies.
