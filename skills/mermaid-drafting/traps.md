# Mermaid traps ledger

Append-only between consolidations. One line per trap:
`T-<id> | symptom | cause | fix`. Every mermaid-drafting session reads this
file first; every render failure or visual defect appends to it.

T-001 | isolated phantom node rendered with literal text `%%` | a bare `%%` line inside the flowchart body parses as a node label | never emit a bare `%%` line; every comment line carries text after `%%` (confirmed 2026-10-08, hr-genie asset-graph)
T-002 | parse error `Expecting NEWLINE got NODE_STRING` before any line number makes sense | comment header (or certain comment forms) before the diagram-type declaration confuses mermaid's diagram detection | make the declaration (`flowchart ...`) line 1; move comments after it. Note: some header comments DO render fine — if unsure, declaration first
T-003 | "visual defect" judged from a low-res PNG turns out to be a misread (edge label `send T6/T7` looked like a typo `sett to J25`) | Read-tool preview downscales large PNGs | inspect at `-s 3` scale or crop the exact region with `sips -c <h> <w> --cropOffset <y> <x>` before changing anything for "cosmetic" reasons
T-004 | grep-verifying the SVG for node text still ships broken diagrams | text presence does not prove visual correctness (phantom nodes pass grep) | visual inspection via PNG + Read is mandatory, not optional (see loop step 5)
T-005 | subgraph layout scrambles when families have internal flows | global direction only, no per-subgraph direction | set `direction TB` (or LR) inside each subgraph
T-006 | mmdc `-w` flag unknown / render fails on width option | mermaid-cli has no `-w`/width flag on current versions | use `-s <scale>` for size; default viewport otherwise
T-007 | render fails `No diagram type detected` when the file starts with `#`-prefixed header lines | `#` is not a mermaid comment (only `%%` is); any non-`%%` text before the declaration breaks diagram detection | convert header lines to `%%` AND move them after the `flowchart` declaration; `%%` header comments placed BEFORE the declaration still fail detection (re-confirmed 2026-10-08, webhook-flow skill test), so T-002's "declaration first" is the only safe placement
