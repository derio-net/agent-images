#!/usr/bin/env bash
# Thin wrapper — delegates to the canonical validator from the
# super-fr plugin installed at the user level.
exec "$HOME/.claude/plugins/marketplaces/derio-net/scripts/validate-plans.sh" "$@"
