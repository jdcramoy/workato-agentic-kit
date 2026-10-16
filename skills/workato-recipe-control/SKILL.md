---
name: workato-recipe-control
description: Start or stop Workato recipes through the Workato Developer CLI when AIRO cannot perform recipe lifecycle operations. Use for one or more recipe IDs, every recipe in a folder, or every recipe in the current CLI project.
---

# Workato Recipe Control

Use the bundled `scripts/workato_recipe_control.py` wrapper. It invokes the
Workato Developer CLI without a shell and previews the exact command unless
`--execute` is present.

For this Workday project, prefer `/Users/YOUR-USER/Documents/Workday/tools/workato-dev.py`
for routine inspection and explicit lifecycle actions. It is portable to
Claude Code and wraps the same Workato Developer CLI. Use this bundled wrapper
when working outside that project or when its narrower interface is preferable.

## Workflow

1. Select the explicit `start` or `stop` mode, and identify exactly one scope:
   `--recipe-id ID [ID ...]`, `--folder-id ID`, or `--all` for the current
   Workato CLI project. For `--all`, verify the current project context before
   execution. Use `--profile NAME` when the user names a profile or environment.
2. If the user supplies only a recipe name, use the Workato CLI's read-only
   listing command to resolve it to an unambiguous ID. Do not guess an ID.
3. Preview the wrapper command without `--execute` when the scope, profile, or
   project context needs verification.
4. Add `--execute` only when the user has explicitly asked to perform that
   precise start or stop operation. A request to create, explain, inspect, or
   preview the command does not authorize recipe mutation.
5. Report the selected action, scope, profile (or active profile), and the CLI's
   result. Do not claim success if the CLI returns a nonzero status.

## Commands

```bash
python3 scripts/workato_recipe_control.py start --recipe-id 12345 12346
python3 scripts/workato_recipe_control.py start --recipe-id 12345 12346 --execute
python3 scripts/workato_recipe_control.py stop --folder-id 987 --profile dev --execute
python3 scripts/workato_recipe_control.py stop --all --profile dev --execute
```

Run commands from this skill directory, or use the script's absolute path.
`--all` relies on the Workato CLI's current project, so never infer that scope
from the current filesystem directory alone. For multiple recipe IDs, the
wrapper calls the CLI once per ID, attempts every requested ID, and returns a
nonzero status if any call fails.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Projects FAQs](../../kb-corpus/docs/en/recipes/projects-faqs.md)
- [View a recipe](../../kb-corpus/docs/en/recipes/read-only-mode.md)
- [Projects](../../kb-corpus/docs/en/projects.md)
- [Testing recipes](../../kb-corpus/docs/en/recipes/testing.md)
<!-- kb-bridges:end -->
