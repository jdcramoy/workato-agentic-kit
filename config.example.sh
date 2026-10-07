#!/usr/bin/env bash
# agentic-workato-kit — per-person configuration.
# Copy to config.sh, fill in your values, then run ./install.sh

# Your macOS home (leave as $HOME unless you know better)
export KIT_HOME="${HOME}"

# Workato workspace IDs (Settings → Workspace). Dev first, prod second.
export WORKSPACE_DEV="3535597"          # e.g. "Workato AHQ | AI Development"
export WORKSPACE_PROD="3535598"         # e.g. "Workato AHQ | AI Production"
export ENV_DEV_NAME="Workato AHQ | AI Development [3535597]"
export ENV_PROD_NAME="Workato AHQ | AI Production [3535598]"

# Jira site + the promotion-story field IDs on YOUR site.
# Find them: create/fetch one past promotion story with GET fields=*all and
# note the customfield ids that hold: manifest URL, target-env cascade,
# source env, story points.
export JIRA_CLOUD_ID="99bd32a1-58a6-41d6-8e61-c98194c68259"
export JIRA_PROJECT="BSYS"
export GOVERNING_EPIC="BSYS-26808"
export FIELD_MANIFEST="customfield_10494"      # manifest URL (text)
export FIELD_ENV_CASCADE="customfield_10446"   # target env cascade (env + child folder option)
export FIELD_SOURCE_ENV="customfield_10588"    # source env (select)
export FIELD_POINTS="customfield_10057"        # story points (number)

# The Claude Code project directory this kit's agents operate from by default
# (the brain-gardener's cron + memory live per-project).
export PROJECT_PATH="${HOME}/Documents/workbench"
