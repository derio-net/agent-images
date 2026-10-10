# Journal: 2026-10-10-hindsight-pg-backoff

<!-- fr:journal kind=repro scope=debug id=8c5160fb594b created=2026-10-10T18:13:36+00:00 -->
### 8c5160fb594b · repro · postgres longrun restarts a fatal bind failure ~1/s forever

Issue #160: with 127.0.0.1:5433 already held in the shared pod netns, postgres exits FATAL 'could not create any TCP/IP sockets' each attempt; s6 restarts every ~1s indefinitely (PIDs to ~523k, 22 OOMKills at 2Gi). Static repro: hermes-agent-shell-hindsight/rootfs/etc/services.d/postgres/ contains only run — no finish, so s6-supervise uses its default: restart after the 1s minimum, never give up.

<!-- fr:journal kind=root-cause scope=debug id=9031601629f9 created=2026-10-10T18:13:42+00:00 -->
### 9031601629f9 · root-cause · postgres service has no finish script, so s6 has no backoff or give-up policy

s6-supervise only stops restarting when finish exits 125 (permanent failure), and only spaces restarts beyond 1s if finish delays. With no finish, a non-transient startup failure loops at 1 Hz forever; each attempt allocates shared buffers before failing to bind, so the loop drives memory to the OOM limit. Single cause; the port collision itself is operator drift tracked in frank.

<!-- fr:journal kind=finding scope=debug id=a03f8787cb57 created=2026-10-10T18:17:53+00:00 state=fixed -->
### a03f8787cb57 · finding [fixed] · postgres finish script: bounded backoff, then exit 125

Fix 2ccfe01: services.d/postgres/finish counts fast failures (<60s uptime); run sleeps 1/2/5/15s between them; 5th fast failure -> exit 125 + one loud stderr diagnostic, service stays down. Clean stops (0, SIGTERM/INT/QUIT) and post-long-uptime crashes reset the count. Pinned first by scripts/tests/test_hindsight_pg_backoff.py (8 failed RED on e9e049a, 67/67 green after). CI smoke step reproduces the collision (python holder on 127.0.0.1:5433, --network container:) and asserts give-up + no further attempts.

<!-- fr:journal kind=finding scope=debug id=8581ffd4a8e3 created=2026-10-10T18:40:12+00:00 state=open -->
### 8581ffd4a8e3 · finding [open] · Unrelated: hindsight-api now fetches tiktoken BPE at startup, fails offline smoke

Branch build run 38075221680 (rerun): postgres starts and listens on 127.0.0.1:5433 (this fix's run/finish work), but hindsight-api crashes every ~13s with NameResolutionError for openaipublic.blob.core.windows.net (tiktoken encoding download) under --network none, so /health never returns 200. Not touched by this diff; main last built green 2026-09-12, so this is dependency drift in the hindsight env since then. Second root cause — held for operator decision per batch rules. (Separately, the first attempt failed on a transient agy installer response; rerun passed.)
