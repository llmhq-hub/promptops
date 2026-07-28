# Error handling: codes, hints, and what to catch

## Run it

```bash
python main.py    # no network, no API key
```

## The contract

Every user-facing PromptOps error carries four fields:

| Field | Purpose |
| --- | --- |
| `code` | Stable `PROMPTOPS_E0XX`. Safe to branch on, grep for, and alert on. |
| `message` | What went wrong, with values interpolated. |
| `hint` | The next command that most likely fixes it. |
| `doc_url` | Deep link into `docs/error-codes.md`. |

**Branch on `.code`, never on message text.** Messages get reworded in any
release; codes do not.

```python
from llmhq_promptops import PromptOpsError
from llmhq_promptops.core import errors

try:
    prompt = manager.get_prompt("greeting", variables)
except PromptOpsError as exc:
    if exc.code == errors.E003_PROMPT_NOT_FOUND:
        ...   # your deploy is wrong
    elif exc.code == errors.E014_RENDER_FAILED:
        ...   # the caller is wrong
```

## Backwards compatibility

`PromptOpsError` subclasses `ValueError` deliberately, so every pre-v0.4.0
`except ValueError` handler keeps working unchanged. New code should catch
`PromptOpsError` to get the structured fields.

## Validate before you render

`validate_variables` tells you what is missing without raising:

```python
problems = manager.get_template("greeting").validate_variables({"name": "Ada"})
# ["Required variable 'tier' is missing"]
```

Full registry: [`docs/error-codes.md`](../../docs/error-codes.md), E001 to E017.
