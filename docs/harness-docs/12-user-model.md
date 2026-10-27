# 12 — User model (preference store + context compiler)

The user model is the harness's memory of the person driving it: a structured
preference store plus a deterministic context compiler. It is installed during
onboarding under a personal name (`<name>-model.py`), so every user's rules,
precedents, drafts, and briefing log are private to them — the kit ships the
engine, never anyone's data.

## What it does

1. **Learn** — rules enter the store two ways: stated (`add`, active
   immediately) or proposed by an agent (`add-draft`, held as a draft until the
   user confirms). Agents can never promote their own rules.
2. **Compile** — on the first prompt of each session, the guardrails mod calls
   `brief --task <prompt>`. The engine scores the store (scope, tag overlap
   with the prompt, recency, correction boost, serve-frequency demotion) and
   injects a bounded markdown briefing (~800 token hard cap).
3. **Evaluate** — `eval` scores correction-episode recall@N: when a mistake
   happened, would the preventing rule have been on screen? Deterministic,
   zero LLM calls anywhere in the engine.

## Store layout

    ~/.claude/knowledge/<name>-model/
      preferences.jsonl      active rules (id, statement, scope, tags, evidence)
      precedents.jsonl       decision precedents (situation, chosen, reason)
      drafts.jsonl           agent-proposed rules awaiting confirmation
      briefings/             served-briefing log (feeds demotion + telemetry)
      eval/                  correction episodes for recall@N

The store directory follows the model name: `sam-model.py` serves
`sam-model/`. The resolution order for the name is `USER_MODEL_NAME` env, then
`~/.claude/knowledge/user-model.conf` (written at onboarding), then the script
filename, then `user`.

## Scopes

| scope | serves when |
|---|---|
| `global` | every session |
| `project:<slug>` | sessions whose cwd is that git repo |
| `task:<type>` | prompts classified as that type (plan, build, review, triage, docs, comms, debug, promote, investigate) |

Untyped prompts still see task-scoped rules weakly, so a task rule with strong
tag overlap can surface on a vague ask — but never outranks a plain global.

## Onboarding flow

`./onboard.sh` asks for the user's first name and three get-to-know-you
questions (a standing rule, writing style, never-do-without-asking).
`./install.sh` then installs the engine as `user-model.py`, copies it to
`<name>-model.py`, writes `user-model.conf`, and seeds the store with the
answers as active rules tagged `onboarding`.

## CLI

    python3 user-model.py add --statement "..." [--rule ...] --scope global|project:x|task:build --tags a,b
    python3 user-model.py add-draft ...          # agent proposals land here
    python3 user-model.py review-list            # pending drafts
    python3 user-model.py confirm pref-001       # promote a draft to active
    python3 user-model.py supersede pref-001 --by pref-002
    python3 user-model.py retract pref-001
    python3 user-model.py brief --task "..."     # what the hook calls
    python3 user-model.py eval                   # recall@8 over correction episodes

Tests: `tests/test_user_model.py` from the kit root
(`python3 -m unittest discover -s tests -v`, 20 tests).

## Constitutional boundary

The engine is scribe + propose only. Agent-proposed rows stay drafts until the
user confirms; nothing is deleted implicitly; every rule carries evidence
(source, ref, date). The briefing is fail-open — a broken store or missing
Python must never block a prompt.
