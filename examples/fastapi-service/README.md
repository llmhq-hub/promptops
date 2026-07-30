# FastAPI: serving prompts in production

The pattern here is lifecycle, not FastAPI. It transfers to Flask, Django, or
any long-lived process.

## Run it

```bash
pip install -r requirements.txt
./setup.sh                    # creates the demo repo + snapshot
uvicorn main:app --reload
```

```bash
curl -X POST localhost:8000/greet -H 'content-type: application/json' \
     -d '{"name": "Ada", "tier": "gold"}'

curl localhost:8000/healthz
```

This example carries its own `requirements.txt` and is **not** exercised by the
PromptOps test suite, so the package itself stays lean.

## Three rules

**1. One manager, built at startup.** Constructing a `PromptManager` per
request re-reads git or the snapshot every time. Build it in `lifespan` and
reuse it.

**2. Pass `AutoResolver` explicitly.** It selects the snapshot in production
and git in development, so `main.py` is identical in both.

**3. Map error codes onto HTTP status.**

| Code | Status | Why |
| --- | --- | --- |
| `E003_PROMPT_NOT_FOUND` | 500 | Your deployment is wrong |
| `E006_SNAPSHOT_MISSING` | 500 | Your image is missing an artifact |
| `E014_RENDER_FAILED` | 400 | The caller omitted a required variable |

Collapsing all of these into 500 hides real client bugs behind what looks like
a server fault.

## Resolve once at boot

`main.py` resolves `greeting` during startup and prints the version. A broken
deploy then fails immediately and visibly, instead of on the first user request
at 3am. `/healthz` exposes the live prompt version, so "what is actually
running right now" is answerable without shell access to the container.
