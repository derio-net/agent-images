# upgrade-session image

**Spec:** `derio-net/frank:docs/superpowers/specs/2026-10-31--life--update-security-lifecycle-design.md` (Part 3, R20-R23, R25, finding s9)

A disposable-pod image for upgrade sessions: omnictl, a talosctl per Talos minor in the upgrade window, a kubectl per Kubernetes minor, and the agent CLIs. A selector (`use-versions`, or UPGRADE_TALOS_MINOR / UPGRADE_K8S_MINOR at start) symlinks the right pair onto PATH, because Talos supports only +/-1 minor of client skew and the session pins per step.

## Base decision

Built FROM `agent-base`, not infra-shell. infra-shell inherits s6-overlay /init, sshd and the agent-session server; s6 needs a writable /run and cont-init writes under /var/log and /var/lib, which defeats a read-only root FS, and a session pod is attached via runs-fr, not SSH. agent-base is already non-root (uid 1000) with tini, node, python, gh and claude. infra-shell's unpinned stable.txt kubectl is also what this image must not inherit.
