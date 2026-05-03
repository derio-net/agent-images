#!/bin/bash
# load-env.sh — populate the calling shell with the secure-agent-pod's
# Kubernetes-injected environment variables.
#
# Source: /run/s6/basedir/env/ (the s6-overlay envdir). Each file under that
# directory has name = env var, content = value, with no trailing newline.
#
# Why an envdir and not /proc/1/environ: under s6-overlay, PID 1 is s6-svscan,
# which deliberately does not carry the K8s envFrom-injected variables that
# tini used to. The envdir is the canonical s6 source and is populated by
# /init at container start.
#
# Why `printf -v` and not `eval` / `export $(...)`: env values can contain
# shell metacharacters (=, ", $, newlines). Literal assignment is the only
# safe choice.
set -a
for f in /run/s6/basedir/env/*; do
  [ -f "$f" ] || continue
  name="$(basename "$f")"
  value="$(< "$f")"
  printf -v "$name" '%s' "$value"
  export "$name"
done
set +a
