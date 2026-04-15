#!/usr/bin/env bash
# Thin wrapper — delegates to the canonical validator from the
# superpowers-for-vk plugin installed at the user level.
exec "$HOME/.claude/plugins/marketplaces/derio-net/scripts/validate-plans.sh" "$@"
