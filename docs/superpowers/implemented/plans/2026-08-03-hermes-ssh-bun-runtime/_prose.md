# hermes-agent-shell-ssh — a JavaScript runtime for the shell

**Spec:** `derio-net/frank:docs/superpowers/specs/2026-08-03--orch--hermes-retrieval-store-sidecar-design.md`
**Issue:** derio-net/frank#759
**Sibling plan:** `derio-net/frank:2026-08-03-hermes-retrieval-store-sidecar`

Adds Bun — and only Bun — to the `hermes-agent-shell-ssh` image, plus a
`profile.d` shim so operator-installed globals resolve in login shells.

## Why the image ships a runtime and not the tool

The client that motivated this is a private Bun/TypeScript CLI. Baking it
would put its name and git URL in a public Dockerfile, which the discretion
rule established on frank#748 exists to prevent. Installing it at runtime
instead is not a compromise here, because `$HOME` in this container is
`/opt/data/home` — a Longhorn PVC. A `bun install -g` lands in
`$HOME/.bun` and survives pod restarts, the same persistent-agent pattern
these shells already use for `claude` and `gh` authentication.

So the image's job is narrow: provide the runtime, and make sure a login
shell can see what the operator installs.

## The two traps this plan is shaped around

**Do not install Bun where Bun wants to go.** Its official installer
targets `~/.bun`, and `$HOME` here is a PVC mount point. Anything the image
bakes under that path is **hidden the moment the volume mounts** — the
image would look correct, build clean, and produce a container with no
`bun` on it. The install therefore goes to `/usr/local/bin` as root, before
the `USER` switch, and only the operator's later global install lives on
the PVC.

**A PATH that is not in `/etc/profile.d` does not exist.** sshd scrubs the
container environment, and this sidecar's PID 1 is sshd itself, so the
`/proc/1/environ` re-export trick used elsewhere in this family reads
proctitle junk here. The shim is the mechanism, not a convenience — and it
must be verified in a **login** shell (`bash -lc`), because
`ssh host -- cmd` and `docker exec` both skip profile.d entirely and would
prove nothing.

## What the registry forces

`scripts/version_audit.py` scans Dockerfiles for versionish `ARG`s and
fails on any pin missing from `PIN_SPECS` — by design, so that "adding a
pin would be a quiet omission" cannot happen. `ARG BUN_VERSION` therefore
comes with a registry entry in the same change, classified `rebuild-only`
because nothing self-updates Bun in-pod.

## CI does not run on your PR

This repo's build workflow has no `pull_request` trigger and its `push`
trigger is restricted to `main`. A PR here is green-looking and entirely
unbuilt, and pushing the branch does not build it either. Phase 3 exists
because validating this change requires an explicit
`gh workflow run build.yaml --ref <branch>`; merging on a green checkmark
alone is merging blind.

## Ordering with frank

Independent to write, independent to merge, joined only at the image pin.
frank's plan back-loads that pin into its own manual phase, and the
scheduled bump workflow re-pins eventually if nobody does it sooner. See
the spec's Sequencing section.
