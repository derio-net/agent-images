# infra-shell

SSH-able shell image carrying the four agent-CLI harnesses inherited from
[`multi-agent-shell`](../multi-agent-shell/) (`claude`, `codex`, `agy`,
`opencode`) **plus** cluster-admin tooling (`kubectl`, `talosctl`,
`omnictl`). Implements the
[multi-harness shell standard](../docs/standards/multi-harness-shells.md)
via inheritance from `multi-agent-shell`.

Intended consumer: a cluster-ops pod where the operator wants the same
multi-harness shell experience plus the three admin CLIs on PATH from
first SSH, without the pentest baggage of `secure-agent-kali`.

## Scope: cluster-ops only

This image deliberately ships **only** the three Kubernetes/Talos/Omni
admin CLIs on top of `multi-agent-shell`. **Pentest packages
(`nmap`, `metasploit`, `sqlmap`, `hydra`, etc.) are
intentionally NOT included.** That separation was the planning-time
decision behind splitting `secure-agent-kali` into a cluster-ops shell
(this image) and a pentest shell (`secure-agent-kali`, untouched in this
batch).

If a specific apt-installable tool is ever needed at runtime, an operator
can layer it via the inventory installer's `apt:` extension rather than
re-baking it into the image.

## Migration note

`secure-agent-kali` is **not removed** by this batch. The Frank-side
switch from `secure-agent-kali` to `infra-shell` for cluster-ops pods is
tracked separately. Both images continue to build in CI.

## Harness manifest

Inherited verbatim from
[`multi-agent-shell` § Harness manifest](../multi-agent-shell/README.md#harness-manifest).
The bootstrap shims, auth commands, credential file paths, and update
commands are identical — `infra-shell`'s rootfs only renames the
multi-agent-shell namespace (state path, MOTD drop-in, reconcile binary)
and adds cluster-admin tooling on top.

## Cluster-admin tooling

| Tool | Version | Install source |
|---|---|---|
| `kubectl` | latest stable (k8s.io `stable.txt` redirect) | `https://dl.k8s.io/release/<stable>/bin/linux/${TARGETARCH}/kubectl` |
| `talosctl` | `v1.9.5` (build arg `TALOSCTL_VERSION`) | `github.com/siderolabs/talos/releases/download/<ver>/talosctl-linux-${TARGETARCH}` |
| `omnictl` | `v0.45.1` (build arg `OMNICTL_VERSION`) | `github.com/siderolabs/omni/releases/download/<ver>/omnictl-linux-${TARGETARCH}` |

Pins + install method are copied verbatim from `kali/Dockerfile` so the
two images stay byte-comparable for the tools they share. When bumping a
version, bump it in both places in the same PR.

## Inventory schema

Inherited from `multi-agent-shell`. Source of truth:
`/etc/infra-shell/inventory.yaml` (mounted ConfigMap on Frank). The
three multi-harness keys (`harnesses`, `mcp-servers`, `skills`) and the
existing keys (`mise`, `npm-global`, `pipx`, `cargo`, `removed`) all
work the same way — see
[`multi-agent-shell/README.md` § Inventory schema](../multi-agent-shell/README.md#inventory-schema)
for the full reference.

## First-boot operator runbook

1. SSH to the pod (`ssh -p 2222 agent@<pod-ip>`).
2. The MOTD prints the auth-status table — all four harnesses show
   `✗ not logged in`.
3. Run each `<h> login` once. OAuth opens in your local browser; the
   credential lands on the PV.
4. Verify the cluster-admin tools are on PATH:
   ```
   kubectl version --client
   talosctl version --client
   omnictl --version
   ```
5. (Optional.) Edit `inventory.yaml` on Frank with the desired
   `harnesses:`, `mcp-servers:`, and `skills:` content; the next pod
   restart (or running `infra-shell-reconcile` interactively) applies
   them.

## Layered install model

Same three-layer model as `multi-agent-shell`:

| Layer | Source | Where it lands | When |
|---|---|---|---|
| 1 — Image baseline | this Dockerfile + the inherited `multi-agent-shell` Dockerfile | image rootfs (immutable) | image build |
| 2 — Inventory | mounted ConfigMap `inventory.yaml` | per-user PV under `$HOME` | every container boot via `cont-init.d/40-shell-inventory` |
| 3 — Interactive | operator typing `mise install …`, `kubectl …`, etc. | per-user PV under `$HOME` | on demand inside the SSH session |

## Operator commands

```bash
# Re-run the inventory installer without restarting the pod
infra-shell-reconcile

# Read the last reconcile log
cat /var/log/cont-init.d/40-shell-inventory.log

# Read the MOTD that prints on every login
cat /var/lib/infra-shell/last-reconcile.motd
```

## Build args

| Arg | Default | Notes |
|---|---|---|
| `BASE_SHA` | `latest` | The `multi-agent-shell` tag/SHA to inherit from. CI passes the SHA of the same workflow run via `build-multi-agent-shell.outputs.sha`. |
| `TALOSCTL_VERSION` | `v1.9.5` | Mirror of the `kali/Dockerfile` pin. |
| `OMNICTL_VERSION` | `v0.45.1` | Mirror of the `kali/Dockerfile` pin. |

`AGENT_USER`, `AGENT_HOME`, `AGENT_UID`, `AGENT_GID` are inherited from
`agent-shell-base` via `multi-agent-shell` (defaults: `agent`,
`/home/agent`, `1000`, `1000`).

## Smoke test

CI job: `smoke-test-infra-shell` in
[`.github/workflows/build.yaml`](../.github/workflows/build.yaml).
Asserts the standard's smoke contract (sshd up under K8s-equivalent
securityContext, every harness reports `--version` cleanly as UID 1000,
`infra-shell-reconcile` produces a clean exit and a non-empty MOTD
against an empty inventory) **plus** the three cluster-admin tools
each report a version as UID 1000.

## Plan / spec

- Standard: [`docs/standards/multi-harness-shells.md`](../docs/standards/multi-harness-shells.md)
- Spec: [`docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md`](../docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md)
- Plan: [`docs/superpowers/plans/2026-06-01-agent-shells-batch/`](../docs/superpowers/plans/2026-06-01-agent-shells-batch/)
