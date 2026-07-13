# Doctrine Engine Companion, backend

Private single user FastAPI service that drives Claude (via the Claude Agent
SDK) over your doctrine engine (`cd_mcp`), authenticated by your Claude
subscription. No Anthropic API key, no per token billing.

## Why this is legal on a subscription

The SDK authenticates with `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`,
which is licensed for individual use. The Google allowlist holds only your own
accounts, so it stays single user. Add other people and you must switch to an
API key.

## What the agent can and cannot do

Allowed: every `christian-doctrine` MCP tool, plus read only `Read`, `Grep`,
`Glob`. Denied: `Edit`, `Write`, `Bash`, web tools, anything unlisted
(`permission_mode="dontAsk"`). Query and retrieval only.

## Prerequisites

1. `cd_mcp` running on the host: `python -m cd_mcp.server` (serves
   `http://127.0.0.1:8765/mcp`).
2. Claude Code CLI logged in once, then a token:

   ```bash
   claude setup-token          # prints the CLAUDE_CODE_OAUTH_TOKEN
   ```

3. Ensure `ANTHROPIC_API_KEY` is NOT set (it would override the token). The app
   refuses to start if it is.

## Install and run

```bash
cd cd_app/backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # fill it in
uvicorn cd_app.backend.main:app --host 127.0.0.1 --port 8080
```

Run it behind your existing reverse proxy with TLS. Keep it on localhost and let
the proxy terminate HTTPS and forward.

## Auth model

Every request needs two headers:

- `Authorization: Bearer <CD_APP_APP_BEARER_TOKEN>` shared secret, constant time
  checked.
- `X-Google-ID-Token: <google id token>` verified against Google, must be minted
  for one of `CD_APP_GOOGLE_CLIENT_IDS` and resolve to an allowlisted email.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/conversations` | New conversation, streams the first turn (SSE). This is "clear". |
| POST | `/conversations/{id}/messages` | Continue a conversation, streams the turn (SSE). |
| GET | `/conversations` | List conversations (archived hidden). |
| GET | `/conversations/{id}/messages` | Full transcript. |
| PATCH | `/conversations/{id}?title=...` | Rename. |
| DELETE | `/conversations/{id}` | Archive (hide). |
| GET | `/healthz` | Liveness, no auth. |

### SSE event shapes

```
{"type":"session","session_id":"..."}   once, early (store it for a new chat)
{"type":"delta","text":"..."}           assistant text chunk
{"type":"tool","name":"..."}            a tool the agent called
{"type":"done","session_id":"..."}      end of turn
{"type":"error","message":"..."}        failure (detail is logged server side)
```

## Notes and limits

- Conversations are the SDK's on disk sessions under `ENGINE_CWD`. No custom
  store to maintain; survives restarts.
- The SDK has no hard delete, so DELETE tags `archived` and the list hides it.
- Pin `claude-agent-sdk` after first install and re verify the message/block
  import names in `agent.py` against that version.
