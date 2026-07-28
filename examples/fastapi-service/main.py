"""Serving prompts from a FastAPI service.

The pattern that matters here is lifecycle, not FastAPI. Three rules:

1. Build ONE PromptManager at startup and reuse it. Constructing one per
   request re-reads git or the snapshot every time.
2. Pass ``AutoResolver`` explicitly. It picks the snapshot in production and
   git in development, so this file is identical in both.
3. Catch ``PromptOpsError`` and map ``.code`` onto HTTP status. A missing
   prompt is a 500 (your deploy is wrong); a missing variable is a 400 (the
   caller is wrong). Collapsing both into 500 hides real client bugs.

Run:
    pip install -r requirements.txt
    ./setup.sh                       # creates a demo repo + snapshot
    uvicorn main:app --reload

Then:
    curl -X POST localhost:8000/greet -H 'content-type: application/json' \\
         -d '{"name": "Ada", "tier": "gold"}'
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from llmhq_promptops import AutoResolver, PromptManager, PromptOpsError
from llmhq_promptops.core import errors


REPO = Path(os.environ.get("PROMPTOPS_REPO", Path(__file__).parent))

# Populated at startup. A module-level singleton is the point: resolution
# should cost nothing per request.
_state: Dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = PromptManager(str(REPO), resolver=AutoResolver(repo_path=str(REPO)))

    # Resolve once at boot so a broken deploy fails immediately and loudly,
    # rather than on the first user request at 3am.
    resolved = manager.resolve("greeting")
    print(
        f"[promptops] greeting resolved from {resolved.source} "
        f"at version {resolved.version}"
    )

    _state["manager"] = manager
    _state["version"] = resolved.version
    _state["source"] = resolved.source
    yield
    _state.clear()


app = FastAPI(title="PromptOps FastAPI example", lifespan=lifespan)


class GreetRequest(BaseModel):
    name: str
    tier: str


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    """Expose which prompt version is live.

    Worth doing: when behavior changes in production, the first question is
    "what version is actually running", and this answers it without shell
    access to the container.
    """
    return {
        "status": "ok",
        "prompt_version": _state.get("version"),
        "resolver_source": _state.get("source"),
    }


@app.post("/greet")
def greet(body: GreetRequest) -> Dict[str, str]:
    manager: PromptManager = _state["manager"]

    try:
        rendered = manager.get_prompt(
            "greeting", {"name": body.name, "tier": body.tier}
        )
    except PromptOpsError as exc:
        # Branch on the code, never on the message: message text can be
        # reworded in any release, codes are stable.
        if exc.code in (errors.E003_PROMPT_NOT_FOUND, errors.E006_SNAPSHOT_MISSING):
            # The deployment is wrong, not the request.
            raise HTTPException(status_code=500, detail=exc.to_dict()) from exc
        if exc.code == errors.E014_RENDER_FAILED:
            # The caller did not supply what the template needs.
            raise HTTPException(status_code=400, detail=exc.to_dict()) from exc
        raise

    # In a real service this is where you would call your model.
    return {"prompt": rendered, "prompt_version": _state["version"]}
