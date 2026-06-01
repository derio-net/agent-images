# Agent Shells Batch Implementation Plan

> **For VK agents:** Use vk-execute to implement assigned phases.
> **For local execution:** Use subagent-driven-development or executing-plans.
> **For dispatch:** Use vk-dispatch to create Issues from this plan.

**Spec:** `docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md`
**Standard:** `docs/standards/multi-harness-shells.md`
**Status:** Draft

**Goal:** Add three new `*-shell` images to the agent-images matrix — `multi-agent-shell`, `hermes-agent-shell`, `infra-shell` — implementing the multi-harness standard so that operators can run `claude`/`codex`/`gemini`/`opencode` (multi/infra) or `hermes` (hermes-leaf) in a single pod-bound shell, with PV-resident auth/skills/MCP and zero-rebuild updates.

**Context:** `paperclip-shell` and `ruflo-shell` are the existing one-harness templates. The recently-shipped v2 bridge cutover (#85) and the mise-activation fix (#56/#91) bring this repo to a clean baseline; the standard (`docs/standards/multi-harness-shells.md`) was drafted alongside this spec and governs the cross-cutting properties (PV-only state, harness manifest, auth MOTD, inventory schema with three new keys, smoke contract). `multi-agent-shell` is the load-bearing addition — it establishes the reusable implementation of the standard, which `hermes-agent-shell` (sibling leaf) and `infra-shell` (`FROM multi-agent-shell`) inherit/mirror.

**Architecture (matches spec § Solution):**

```
agent-base
└── agent-shell-base
    ├── hermes-agent-shell         (Phase 2 — hermes only, LiteLLM-wired BYOK)
    └── multi-agent-shell          (Phase 1 — claude+codex+gemini+opencode)
        └── infra-shell            (Phase 3 — multi + kubectl/talosctl/omnictl)
```

CI gets a second intermediate-base job (`build-multi-agent-shell`) parallel to `build-shell-base`, three new `build-children` matrix entries, three new smoke-test jobs, and three additions to `dispatch-frank.needs`. `secure-agent-kali` stays in the matrix; its removal is a separate Frank-side concern.

**Tech stack:** Dockerfile, s6-overlay (`cont-init.d`), `/etc/profile.d/` drop-ins for MOTD, bash + bats for the inventory installer + tests, GitHub Actions for CI.

**Scope boundary (mirrors spec):**

- **In scope:** Three new image dirs (`Dockerfile` + `rootfs/` + `README.md` per the standard's checklist), one new intermediate-base CI job, three matrix entries, three smoke-test jobs, README cross-links, the install-inventory.sh extension for the three new schema keys, the auth-status MOTD profile.d drop-in.
- **Out of scope:** Frank-side pod/service manifests, ESO mappings, `secure-agent-kali` removal, the actual list of MCP servers and skills the operator pre-loads (schema only — data lives in Frank ConfigMaps), cross-harness skill unification, hermes self-hosting beyond the bootstrap.

**Decisions taken before planning** (see spec brainstorm):

- One plan, three dependency-ordered phases (not three separate plans).
- `infra-shell` ships **cluster-ops only** — `kubectl`/`talosctl`/`omnictl`; pentest packages do **not** get baked in (operators can layer them via the inventory's `apt` extension if ever needed).

**Items deferred to step execution** (impl-time lookups; not architectural choices):

- Upstream npm package names + install pins for `codex`, `gemini`, `opencode`.
- Each harness's exact credential-file path on disk.
- `hermes` upstream repo URL, install method, and initial `HERMES_GIT_REF`.

These are confirmed by the executing agent inside the phase that needs them — the design is robust against any specific choice as long as the standard's properties hold.

## Phase dependencies

```
Phase 1: multi-agent-shell + standard impl + CI intermediate    depends_on: []
Phase 2: hermes-agent-shell                                     depends_on: [1]
Phase 3: infra-shell (FROM multi-agent-shell)                   depends_on: [1]
```

Phases 2 and 3 are independent of each other and can be executed in parallel after Phase 1 merges; the dependency on Phase 1 is for the standard's reusable scaffolding (inventory-installer extension, auth-MOTD drop-in) which Phase 1 establishes as the reference and which Phases 2 and 3 mirror per-image.
