---
name: blast-radius
description: Compute what breaks if a Workato asset fails or changes — dependents, shared connections, downstream tables, MCP servers serving it. Use before touching a live recipe, when assessing a P1's urgency, or when Josh asks "what depends on this", "what's the blast radius", "what breaks if".
---

# Blast radius

Every P1, every push, every deprecation question gets the same answer shape:
**asset → dependents → consumers → verdict on urgency.**

## Procedure

1. **Anchor the asset.** recipe_id / connection / table / connector. Never
   radius a name you haven't resolved to an ID (search discipline).
2. **Direct dependents.** Dependency tracker: `search_recipe_dependencies`
   with the recipe/connection/object. Dedup per-recipe (the tracker returns
   one row per step).
3. **Shared surfaces.** Same connection used by other recipes
   (`list_connections` + tracker by connection name); same data table; same
   MCP server serving the skill (a dead tool breaks every Genie calling it).
4. **Consumers.** Who calls this recipe as a function; which schedules or
   Genies depend on its output.
5. **Verdict.** One line: "N assets depend on this; M are running; the worst
   consumer is X." Urgency = running dependents × business criticality.

## Output shape

- Direct dependents with URLs (always linked)
- Shared-connection cohort (who else dies if the connection dies)
- The verdict line, stated as priority with evidence

## Rules

- Reads only. This skill never mutates.
- Empty results twice = report the gap, don't widen the search (two-strike).
- An unknown blast radius is stated as unknown, never rounded to "low".
