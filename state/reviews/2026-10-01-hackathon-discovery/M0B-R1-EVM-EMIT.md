# M0b — R1 resolved empirically: EVM emit / view against local GLSim

Date: 2026-10-01. Artifact under test: `contracts/probe_r1.py`, `tests/direct/test_probe_r1.py`.

## Command

    cd /home/unify/mys
    .venv/bin/python -m pytest tests/direct/test_probe_r1.py -v -s

## Observed output

    DETAIL: view raised AttributeError: 'Target.ViewProxy' object has no attribute 'parent' | emit ok
    VIEW_OK: 0 EMIT_OK: 1
    1 passed in 0.25s

## Conclusion: local GLSim can prove NEITHER EVM view NOR EVM emit

Two independent defects, both fatal to verifying M3 locally.

### Defect 1 — SDK bug: `EthCall` / `.view()` is broken in the pinned SDK build

`_generate_view` in `genlayer/gl/_internal/eth.py:23` reads `self.parent.address`, but
`_generate_methods` in `genlayer/py/evm/generate.py:101` only ever defines `_proxy_parent`.
The attribute does not exist, so **every** `.view()` call raises `AttributeError`.

This is a defect in SDK hash `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`
(the hash the brief pins), not a harness gap. Any published doc example calling
`token.view().total_supply()` is broken on this build.

### Defect 2 — Harness gap: `EthSend` / `.emit()` silently no-ops and *looks* successful

`gltest/direct/wasi_mock.py::_handle_gl_call` handles `Return`, `Rollback`, `Trace`, `Sandbox`,
`RunNondet`, `WebRequest`/`GetWebsite`, `WebRender`, `ExecPrompt`, plus a
`DeployContract`/`CallContract`/`PostMessage` hook. There is **no `EthSend` or `EthCall` branch**.

So `gl_call()` returns `2**32 - 1`; `genlayer/gl/_internal/gl_call.py::gl_call_generic` maps that
sentinel to `Lazy(lambda: None)`; and `_generate_send` calls `.get()`, which returns `None`
**without raising**.

Consequence: `emit().freeze(...)` reports success and returns normally while doing nothing.
This is worse than an error — an assertion that the emit succeeded would pass green and prove
nothing. `EMIT_OK: 1` above is exactly this false positive, and it is why the product contract
must never treat a local emit as verified.

### Decision

R1 cannot be closed on local GLSim. M3 (freeze emitted to the demo target) must be verified on
**studio-dev** against real GenVM, where `EthSend` is handled by the node.

Two SDK preconditions that must hold on studio-dev, to be checked there:
1. `EthSend` is handled by the real GenVM executor (not the local stub).
2. EVM writes are only emitted on finality, so the emit must sit **outside** the nondet block,
   after `run_nondet` returns.

If studio-dev also refuses `EthSend`, the documented watcher fallback applies (R1 mitigation in
`HANDOFF.md` §4): the contract publishes an attested verdict payload that an in-repo watcher
reads and turns into the EVM call.

## Unrelated but blocking: two doc/SDK mismatches that cost real debugging time

Both are cases where following the published docs verbatim produces a contract that will not import.

1. **`@gl.evm.contract_interface` View/Write methods must declare positional-only parameters.**
   `genlayer/py/evm/generate.py:87` asserts `param_data.kind == inspect.Parameter.POSITIONAL_ONLY`.
   The published example in the EVM-interaction docs writes `def freeze(self, reason: str, until: u256) -> None: ...`
   with no `/`, which fails at import with a bare `AssertionError`. Correct form:

       class Write:
           def freeze(self, reason: str, until: u256, /) -> None: ...

2. **`gl.nondet.web` response field is `status`, not `status_code`.**
   The web-access docs show `response.status_code`. `genlayer/gl/nondet/web.py::Response` declares
   `status: int`, `headers`, `body`. Also `body` is `bytes | None`, so it must be `.decode()`-ed.

Also required but not spelled out in the brief: the contract class must inherit `gl.Contract`
(`genlayer/gl/genvm_contracts.py:423`), exactly one subclass per module, or the loader reports
`No contract class found`. And `Address`-typed storage needs a real `Address` instance —
passing a `str` raises `AttributeError: 'str' object has no attribute 'as_bytes'`.
