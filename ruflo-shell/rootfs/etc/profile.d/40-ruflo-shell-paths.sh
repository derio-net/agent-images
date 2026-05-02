# 40-ruflo-shell-paths.sh — Wire mise shims and cargo's bin dir into the
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
