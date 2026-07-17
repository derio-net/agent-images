# 40-multi-agent-shell-paths.sh — Wire mise shims and cargo's bin dir into the
# operator's interactive PATH. Both directories live under $HOME on the PVC,
# so they survive image bumps but only exist after the inventory installer (or
# the operator) has installed something via the corresponding manager.
#
# Activated for every login shell (and re-sourced by ~/.bashrc).

case ":$PATH:" in
    *":$HOME/.local/share/mise/shims:"*) ;;
    *) PATH="$HOME/.local/share/mise/shims:$PATH" ;;
esac

case ":$PATH:" in
    *":$HOME/.cargo/bin:"*) ;;
    *) PATH="$HOME/.cargo/bin:$PATH" ;;
esac

# pipx puts user-installed entry points here.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) PATH="$HOME/.local/bin:$PATH" ;;
esac

export PATH

# Point npm's global prefix at the PV-resident, agent-owned ~/.local so a
# harness self-update (`npm install -g @openai/codex` / `opencode-ai`, the
# mechanism the Dockerfile bootstrap documents) writes to the writable home
# volume instead of the root-owned /usr default. Without it the update dies
# `EACCES: permission denied, rename '/usr/lib/node_modules/@openai/codex'` and
# the harness is stuck at the baked pin. ~/.local/bin is PATH-preferred above,
# so the self-updated build shadows the /usr bootstrap; the update persists on
# the PV across restarts and image bumps. Set only when unset so an operator's
# explicit ~/.npmrc prefix still wins.
: "${NPM_CONFIG_PREFIX:=$HOME/.local}"
export NPM_CONFIG_PREFIX
