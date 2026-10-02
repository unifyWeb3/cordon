# Project state — adjudicated emergency pause

Updated 2026-10-02. Repo: `/home/unify/mys` (git initialised during this build, 7 commits).

## What exists

| Milestone | Status | Evidence |
|---|---|---|
| M0 consensus gate | **done** | 38 hermetic tests, `tests/direct/` |
| M0b EVM-emit gate | **done — negative result** | `M0B-R1-EVM-EMIT.md` |
| M1 contract v1 | **done** | `contracts/emergency_halt.py`, 11 methods |
| M2 evidence + auto-expiry | **done** | `tests/direct/test_freeze_and_expiry.py` |
| M3 EVM action | **partial** | verdict + expiry verified live; EVM `emit()` **unverified** |
| M4 frontend | **done** | `web/`, `next build` EXIT=0 |
| M5 demo target | **partial** | `demo-target/HaltablePool.sol` written, **not deployed** |
| M6 adversarial script | **done** | `deploy/submit_proof.py`, `tests/direct/fixtures.py` |
| M7 docs | **done** | `README.md`, `docs/integration.md`, `deploy/README.md` |
| M8 rubric self-review | **done** | `M0-RUBRIC-SELF-REVIEW.md` — recommendation: **do not submit yet** |
| M9 demo video + post | **not started** | — |

## Deployed

`0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774b` — Studionet (chain 61999).
Not studio-dev: contract execution is broken there (see below).

## Verification status

| Check | Command | Result |
|---|---|---|
| Hermetic suite | `.venv/bin/python -m pytest tests/direct/ -q` | **38 passed** in 81.88s |
| Contract lint + SDK validation | `.venv/bin/genvm-lint check contracts/emergency_halt.py` | **passed** (11 methods) |
| Frontend types | `web/node_modules/.bin/tsc --noEmit` | **clean** |
| Frontend build | `web/node_modules/.bin/next build` | **EXIT=0**, 4/4 pages static |
| Live consensus | `deploy/submit_proof.py` | MAJORITY_AGREE on 3 live cases |

Suite runtime is ~82s rather than ~25s because an unrelated Rust build on the shared host is
loading the CPU. Test count and behaviour are unchanged.

## Environments

| venv | Contents | Purpose |
|---|---|---|
| `.venv` | `genlayer-test==0.28.0` (pins `genlayer-py==0.9.0`), `genvm-linter==0.10.0` | tests |
| `.venv-deploy` | `genlayer-py==0.18.0` | deploy / submit |

`genlayer-test` hard-pins `genlayer-py==0.9.0`, so the test env cannot be upgraded without
breaking the pinned harness.

## Known-broken things

1. **studio-dev (61997) cannot execute contracts.** Every deploy, including the 20-line
   `contracts/minimal_probe.py`, finalizes `FINISHED_WITH_ERROR` / `MAJORITY_AGREE` /
   `num_of_rounds=0`, with and without `leaderOnly`, and registers no contract. Identical code
   runs on Studionet. `gen_dbg_traceTransaction` is also absent there.
2. **EVM `emit()` unverified.** Silent no-op under local GLSim (`gltest`'s WASI mock has no
   `EthSend` branch; `gl_call_generic` maps the failure sentinel to `None` and `_generate_send`
   swallows it). Never observed on real GenVM.
3. **`.view()` (`EthCall`) is broken in the pinned SDK** `1jb45aa8…`: `_generate_view` reads
   `self.parent.address` but the generated proxy only defines `_proxy_parent`.

## Durable lessons (see MEMORY.md)
