# The agentic Workato kit — a one-page overview

## What it is

A development harness wrapped around Claude Code that turns AI-assisted
Workato work from "a smart intern with amnesia" into a compound asset. It
is eight layers: enforcement mods (the standing rules become code that
cannot be forgotten), playbook skills (lessons load into every session),
a Developer API wrapper for what the platform tools do not expose, watcher
agents that inspect the estate on schedules and corroborate each other
over a shared bus, a curated knowledge system that captures lessons and
re-verifies them against live behavior, a governed promotion pipeline,
a nightly dreamer that mines every session to improve the harness itself,
and a RAG++ knowledge base over all Workato documentation.

## The memory system

Everything the harness learns lives in one git-versioned tree with three
tiers: fluid knowledge files (prose, curated daily), a structured claim
ledger (facts with verdicts and re-verification dates), and the always-on
instruction layer (the rules every session loads). On top of it sits a
fractal memory index: the same schema at every scale (topic, file, section,
chunk), so a question is answered at the coarsest depth that works and
drills to exact evidence only when needed — roughly 10x less context per
memory question, with completeness mechanically audited. Files stay the
source of truth; you write memory exactly as you would anywhere in Claude
Code ("remember X"), and the index maintains itself.

## The Workato KB

A local, nightly-synced corpus: all Workato product documentation (via the
docs site's llms.txt Markdown twins), the product changelog, the blog, the
Enterprise Integration Patterns catalog, the architecture-canon GitHub
repos, and this team's own Confluence. Retrieval is hybrid: full-text plus
dense vectors plus a cross-encoder rerank, with two modulation layers
(information density and term concentration) and a confidence gate that
expands the search when the answer looks weak. Agents consult it before
guessing or asking you; the `/kb` command is the human front door. A year
of the team's closed Jira bugs is distilled into a case base, so diagnosis
starts from "what happened last time this exact thing broke."

## What adopting looks like

    git clone https://github.com/Workato-All/workato-agentic-kit.git
    cd workato-agentic-kit
    ./onboard.sh     # ~14 questions; tokens go to your keychain, not files
    ./install.sh     # installs mods, agents, skills, the knowledge scaffold, and clones the KB
    ./verify.sh      # doctor: green means go

Requirements: Claude Code 2.1.287+, git, python3, jq. You also connect your
own AIRO MCP (dev and prod) plus Atlassian; the KB syncs nightly on a
launchd schedule it installs itself.

## The boundary

Your memory is yours. The kit ships the organism; each person's knowledge
tree grows from empty with their own lessons. Nothing in your tree, your
tickets, or your Confluence syncs to anyone else, and nothing here phones
home.

Verdict: it is the accumulated working memory of an enterprise Workato
developer, wired to notice its own mistakes — and it is one clone away.
