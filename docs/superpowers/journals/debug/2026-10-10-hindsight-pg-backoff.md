# Journal: 2026-10-10-hindsight-pg-backoff

<!-- fr:journal kind=repro scope=debug id=8c5160fb594b created=2026-10-10T18:13:36+00:00 -->
### 8c5160fb594b · repro · postgres longrun restarts a fatal bind failure ~1/s forever

Issue #160: with 127.0.0.1:5433 already held in the shared pod netns, postgres exits FATAL 'could not create any TCP/IP sockets' each attempt; s6 restarts every ~1s indefinitely (PIDs to ~523k, 22 OOMKills at 2Gi). Static repro: hermes-agent-shell-hindsight/rootfs/etc/services.d/postgres/ contains only run — no finish, so s6-supervise uses its default: restart after the 1s minimum, never give up.

<!-- fr:journal kind=root-cause scope=debug id=9031601629f9 created=2026-10-10T18:13:42+00:00 -->
### 9031601629f9 · root-cause · postgres service has no finish script, so s6 has no backoff or give-up policy

s6-supervise only stops restarting when finish exits 125 (permanent failure), and only spaces restarts beyond 1s if finish delays. With no finish, a non-transient startup failure loops at 1 Hz forever; each attempt allocates shared buffers before failing to bind, so the loop drives memory to the OOM limit. Single cause; the port collision itself is operator drift tracked in frank.
