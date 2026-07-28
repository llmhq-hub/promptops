# Migrating from Hardcoded Prompts

Moving an existing codebase off string literals, incrementally, without a
rewrite and without a flag day.

The end state: prompts live in `.promptops/prompts/*.yaml`, are versioned by
git, and can be answered for after an incident. The path there is one prompt
at a time.

## Before you start

You do not need to migrate everything. Migrate the prompts where the questions
"what changed?" and "what was running when this broke?" actually come up.
A one-line system prompt that has not changed in a year can stay where it is.

Good first candidates: prompts that have been edited more than twice, prompts
whose output someone has complained about, prompts with more than one variable.

## Step 1: initialize

```bash
promptops init repo
```

This creates `.promptops/` and nothing else. Since v0.4.0 it does **not**
touch `.git/hooks/`. Automatic version bumping is a deliberate second step:

```bash
promptops hooks install
```

You can skip hooks entirely and tag versions manually. See
[`examples/hooks-lifecycle/`](../examples/hooks-lifecycle/) for what they do
and how to remove them.

## Step 2: move one prompt

Start from what you have:

```python
# app/agents.py
SUPPORT_PROMPT = f"""
You are a support agent for {company}.
Answer in at most {max_words} words.
Escalate anything about refunds.
"""
```

Create the prompt:

```bash
promptops create prompt support-agent
```

That scaffolds `.promptops/prompts/support-agent.yaml`. Fill it in:

```yaml
metadata:
  id: support-agent
  description: Customer support agent system prompt
  models:
    default: gpt-4-turbo
template: |
  You are a support agent for {{ company }}.
  Answer in at most {{ max_words }} words.
  Escalate anything about refunds.
variables:
  company:
    type: string
    required: true
  max_words:
    type: string
    required: true
```

The translation is mechanical: f-string `{company}` becomes Jinja
`{{ company }}`, and every interpolated name gets an entry under `variables:`.

**Declare your variables.** PromptOps treats a variable used in the body but
never declared as required anyway, so undeclared ones still work, but
declaring them is what lets `promptops test diff` tell you when you have
broken a caller.

## Step 3: swap the call site

```python
# app/agents.py
from llmhq_promptops import get_prompt

prompt = get_prompt("support-agent", {
    "company": company,
    "max_words": max_words,
})
```

`get_prompt` defaults to `AutoResolver` (since v0.3.3), so this works both in
a git checkout and in a production container shipping only a snapshot.

In a long-lived service, build one `PromptManager` at startup instead of
calling the module-level helper per request. See
[`examples/fastapi-service/`](../examples/fastapi-service/).

## Step 4: verify before you delete the literal

Do not delete the original string until you have compared outputs.

```python
assert get_prompt("support-agent", vars) == SUPPORT_PROMPT
```

A one-off assertion is enough; the point is to catch a translation slip
(a missed variable, a lost newline) while the original is still in front of
you. Then delete the literal.

Watch trailing newlines: YAML block scalars (`|`) keep the final newline,
while `|-` strips it. If your assertion fails by exactly one character, that is
why.

## Step 5: commit, and you have history

```bash
git add .promptops/prompts/support-agent.yaml
git commit -m "feat: move support agent prompt into promptops"
```

From here:

```bash
promptops history support-agent      # every version, and what shipped
promptops test diff support-agent    # what changed, and does it break callers
```

## Repeat, then wire up production

Once two or three prompts have moved and the workflow feels right, do the
production wiring once:

- [Production deployment guide](production-deployment.md): snapshot pipeline,
  Docker, CI
- [Day 0 playbook](day-0-playbook.md): rehearse an incident before you have one
- Copy [`examples/github-actions/promptops-diff.yml`](../examples/github-actions/promptops-diff.yml)
  so prompt changes get reviewed like code changes

## Common snags

**"My prompt is built conditionally."**

```python
prompt = BASE
if user.is_premium:
    prompt += PREMIUM_ADDENDUM
```

Use Jinja conditionals and pass the flag as a variable:

```yaml
template: |
  {{ base_instructions }}
  {% if is_premium %}
  Offer priority scheduling.
  {% endif %}
variables:
  is_premium:
    type: boolean
    required: false
    default: false
```

Keep the branching in the template so the whole prompt is visible in one
place. A prompt assembled across three files cannot be usefully diffed or
blamed.

**"I want to share a common preamble across prompts."**

Not with `{% include %}`. PromptOps renders in a sandbox with no template
loader, so include, import, from, and extends all fail with
`PROMPTOPS_E012` at snapshot build time. Either inline the shared text into
each prompt, or compose in application code by rendering two prompts and
joining them. Self-contained prompts are what make a single blame answer
complete.

**"My prompts are in a database, not source."**

Export them to YAML once and treat source as the origin from then on.
A prompt that can change without a commit cannot be versioned, diffed, or
blamed, which is most of what PromptOps offers.

**"I have hundreds of prompts."**

Migrate the ones that change. The rest can stay hardcoded indefinitely.
Migration is not a completeness exercise.

## Related

- [`examples/error-handling/`](../examples/error-handling/): what to catch once
  prompts resolve at runtime
- [Error codes](error-codes.md)
- [Migration guide, v0.3 to v0.4](migration-v0.3-to-v0.4.md), if you are
  upgrading rather than adopting
