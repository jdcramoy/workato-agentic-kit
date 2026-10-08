# workato-kb — RAG++ documentation pipeline (kit package)

Local RAG++ knowledge base over documentation sources. Installed and battle-tested
in Josh's harness 2026-10-08 (state and lessons: knowledge/projects/workato-kb.md).

**Included here: the pipeline CODE only.** Corpus data (`~/.claude/workato-kb/`)
is per-person and must never be committed — the BT Confluence sources are internal.
The `.gitignore` copied with the package enforces this; do not remove it.

## What a new person does

1. Copy `kb/` to a local repo (`~/Documents/workato-kb`), create the venv:
       cd ~/Documents/workato-kb && python3.12 -m venv .venv
       .venv/bin/pip install sentence-transformers sqlite-vec torch html2text pypdf
2. First sync + index (docs/changelog/blog/inspiration/github/eip work with no auth;
   Claude docs need none either):
       .venv/bin/python -m kb.sync --no-embed   # quick crawl pass
       .venv/bin/python -m kb.indexer           # chunks + embeddings (slow first run)
       .venv/bin/python -m kb.pmi build && .venv/bin/python -m kb.entropy score
3. Confluence (only if you have BT space access): create an API token at
   id.atlassian.com, then:
       security add-generic-password -s atlassian-confluence -a <your-atlassian-email> -w <TOKEN>
   and set `KEYCHAIN_ACCOUNT` in `kb/confluence_sync.py` to your email.
   Confluence corpora are LOCAL-ONLY by policy. Never commit, back up, or share them.
4. Schedule the nightly sync (see schedules/kb-sync-nightly.plist).
5. Install the `/kb` slash command and the `workato-kb` skill (skills/ dir of this kit).

## Sources (9)

docs.workato.com (llms.txt markdown twins), product-hub changelog (WP cat 443),
blog + The Connector (one WP install: blog2workato.wpengine.com), Automation
Inspiration (WP cat 436), GitHub architecture canon (3 repos), EIP site,
Claude platform docs (llms.txt), BT Confluence extbt/intbt (gated, local-only).

## Known platform gotchas (learned the hard way)

- blog and The Connector share ONE WordPress install; /blog/wp-json 301s to
  /the-connector/wp-json. Crawl the origin host once.
- The changelog archive HTML renders links client-side — use wp-json category 443.
- v1 Confluence content/search CQL arrives empty server-side on our tenant —
  sync via v2 space-pages pagination + sha compare instead.
- Atlassian scoped-API-token auth needs the EXACT account email (dots matter).
- macOS + high-concurrency DNS = Errno 8 flakes; retry with backoff, keep
  Confluence workers at 2.
- sqlite-vec must be loaded per-connection (`sqlite_vec.load(db)`) — `vec0`
  is not built-in.
- python3.14 (current homebrew) has no torch wheels; pin the venv to python3.12.
