# Journal: hindsight-offline-smoke

<!-- fr:journal kind=repro scope=debug id=a589b2dbe258 created=2026-10-11T16:38:25+00:00 -->
### a589b2dbe258 · repro · Offline smoke: hindsight-api crash-loops fetching cl100k_base.tiktoken

Branch build run 38075221680 (fix/batch-hindsight-pg-backoff @ cffe756), job smoke-test-hermes-agent-shell-hindsight: container run with --network none; hindsight-api dies in MemoryEngine.__init__ -> _get_tiktoken_encoding() -> token_encoding.get_token_encoding() -> tiktoken.get_encoding('cl100k_base') -> requests to openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken -> NameResolutionError. s6 restarts it (14 tracebacks in 180s); /health never 200. Main's push builds 38123865538 and 38153833283 fail the same way. Last green: 34713830785 (2026-09-12), /health 200 after 16s, no tiktoken fetch.

<!-- fr:journal kind=ruled-out scope=debug id=d35bb2536d3b created=2026-10-11T16:38:28+00:00 -->
### d35bb2536d3b · ruled-out · Not a hindsight-api or tiktoken version change

Diffed 'Successfully installed' between green build (run 34713830785) and red (38075221680): hindsight-api-slim 0.8.5 and tiktoken 0.14.0 are identical in both. hindsight 0.8.5's eager get_encoding call in MemoryEngine.__init__ ran in green too, so in green something else made it resolve offline.

<!-- fr:journal kind=hypothesis scope=debug id=bae624d99617 created=2026-10-11T16:38:32+00:00 -->
### bae624d99617 · hypothesis · litellm 1.104 stopped setting TIKTOKEN_CACHE_DIR at import

litellm's default_encoding.py sets os.environ['TIKTOKEN_CACHE_DIR'] to its bundled litellm_core_utils/tokenizers dir (which holds cl100k_base, file 9b5ad71b...). In 1.100.1, litellm_core_utils/token_counter.py imports default_encoding at module level, so importing litellm (hindsight imports litellm.exceptions) set the env var as a side effect, and hindsight's tiktoken lookup hit the bundled file offline. In 1.104.2 (unpinned transitive dep; drifted 1.100.1 -> 1.104.2) the only import of default_encoding is inside a function in rust_bridge/tokenizer.py, so the env var is never set.

<!-- fr:journal kind=root-cause scope=debug id=e059fe2d59c8 created=2026-10-11T16:38:35+00:00 -->
### e059fe2d59c8 · root-cause · Image was offline only by accident of litellm's import-time side effect

Verified: fresh env, python -c 'import litellm.exceptions; import litellm' prints TIKTOKEN_CACHE_DIR=<site-packages>/litellm/litellm_core_utils/tokenizers under litellm 1.100.1 and None under 1.104.2 (tiktoken 0.14.0 in both). The image never baked a tiktoken encoding nor set TIKTOKEN_CACHE_DIR; its offline startup relied on litellm mutating the env on import. litellm 1.104 made that import lazy, so hindsight-api's eager cl100k_base lookup goes to the network and crash-loops under --network none. One root cause; #163's collision step is downstream of it (same job, never reached).

<!-- fr:journal kind=finding scope=debug id=173047ec3c23 created=2026-10-11T16:51:25+00:00 state=fixed -->
### 173047ec3c23 · finding [fixed] · Bake cl100k_base into TIKTOKEN_CACHE_DIR=/opt/hindsight-tiktoken

Fix (db30407): Dockerfile sets ENV TIKTOKEN_CACHE_DIR=/opt/hindsight-tiktoken and runs tiktoken.get_encoding('cl100k_base') at build time (asserting the dir is non-empty), chowned to UID 1000 with the rest of the baked stack. This removes the dependence on litellm's import-time env mutation, matching the existing bake-by-path approach for the BGE model. Failing test first (7ef745a): new first step in smoke-test-hermes-agent-shell-hindsight runs the image's python under --network none with litellm NOT imported and asserts cl100k_base encodes 'hello world' to [15339, 1917]. Rejected alternatives: pinning litellm<1.104 (keeps the accidental coupling); pointing TIKTOKEN_CACHE_DIR at litellm's package dir (couples to litellm's internal layout). Validation: branch build run 38157168934.

<!-- fr:journal kind=finding scope=debug id=red-proof created=2026-10-11T16:53:38+00:00 state=fixed -->
### red-proof · finding [fixed] · New smoke step is red against main's image

Ran the new #165 step body locally (host docker, x86_64) against ghcr.io/derio-net/hermes-agent-shell-hindsight:5c05aaaf52d6 (main's latest published hindsight image): exit=1, requests ConnectionError to openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken — the same failure as the CI health smoke, now caught in seconds by a targeted assertion.
