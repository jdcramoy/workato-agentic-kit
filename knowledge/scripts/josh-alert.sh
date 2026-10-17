#!/bin/bash
# josh-alert.sh — surface an attention-needed moment to Josh.
# Layer 1 (guaranteed): afplay chime — independent of notification settings/Focus
#                        (proven 2026-10-15: banner suppressed, chime heard).
# Layer 2: terminal-notifier banner (own Notification Center identity; needs
#          System Settings → Notifications → terminal-notifier → Allow) with
#          osascript fallback if the binary is missing or denied.
# Josh ruling 2026-10-15: NEVER --voice (too noisy on calls; flag kept but unused).
# Usage: josh-alert.sh "title" "message" [--voice]
TITLE="${1:-Attention needed}"
MSG="${2:-An agent needs your action}"
afplay /System/Library/Sounds/Glass.aiff &
TN="/opt/homebrew/Cellar/terminal-notifier/3.1.0/terminal-notifier.app/Contents/MacOS/terminal-notifier"
if [ -x "$TN" ]; then
  "$TN" -title "$TITLE" -subtitle "Orca browser agent" -message "$MSG" -sound Glass >/dev/null 2>&1
else
  osascript -e "display notification \"$MSG\" with title \"$TITLE\" subtitle \"Orca browser agent\" sound name \"Glass\""
fi
if [ "$3" = "--voice" ]; then
  say -v Samantha "$TITLE. $MSG" &
fi
