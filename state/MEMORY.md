# Memory — durable decisions and constraints

Updated 2026-10-02.

## Decisions

- **Deploy target is Studionet (61999), not studio-dev (61997).** studio-dev cannot execute
  contracts at all, verified with a 20-line probe. The brief specified studio-dev; this is a
  reported deviation, not a silent substitution. `deploy_studio_dev.py` still defaults to
  studio-dev.
- **Two virtualenvs, deliberately.** `genlayer-test==0.28.0` hard-pins `genlayer-py==0.9.0`, so
  the pinned test harness and a current deploy SDK cannot coexist in one environment.
- **`evidence_mode="jsonrpc"` is the default.** The contract POSTs one batched JSON-RPC call to
  the target chain's public RPC, so the live demo needs no hosting, no indexing service and no
  API key. `digest` mode exists for hermetic tests and for callers who want to supply their own
  reduced evidence.
- **Consensus compares only the verdict enum.** Never the rationale. This is enforced by a test
  (`test_validator_ignores_rationale`) rather than by convention, because it is the one property
  that makes consensus work at all.

## Constraints worth remembering

- **Never put wall-clock time in an Intelligent Contract.** Use `gl.message_raw["datetime"]`.
  Leader and validators are not guaranteed to share a clock. Cost a real bug: `_iso_now()`
  originally called `datetime.now()`.
- **Pin `sdk_version` in every `direct_deploy`.** gltest picks the lexicographically newest
  tarball in `~/.cache/gltest-direct`, and running `genvm-lint` drops differently-named bundles
  into that same directory. Without pinning, `genvm-lint check` breaks the whole suite.
- **`genvm-lint` and `gltest` share a cache directory.** Treat running one as a side effect on
  the other.

## SDK gotchas that cost real debugging time

Each of these is a case where the published docs are wrong or incomplete, verified against
`genlayer-test==0.28.0` + SDK hash `1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`:

| Gotcha | Detail |
|---|---|
| `@gl.evm.contract_interface` View/Write methods need **positional-only** params (`/`). | Omitting `/` fails at import with a bare `AssertionError` from `generate.py:87`. The published example omits it. |
| `gl.nondet.web` response field is `.status`, **not** `.status_code`. | `Response` declares `status: int`, `headers`, `body: bytes \| None`. Docs say `status_code`. |
| Contract classes must inherit `gl.Contract`. | Otherwise the loader reports `No contract class found`. Only one subclass per module. |
| `Address`-typed storage needs a real `Address`. | Assigning a `str` raises `AttributeError: 'str' object has no attribute 'as_bytes'`. |
| Storage containers cannot be constructed in `__init__`. | `TreeMap[str, X]()` raises `this class can't be instantiated by user`. Annotate the attribute; the generated storage initialises it. |
| `.view()` / `EthCall` is broken. | `_generate_view` reads `self.parent.address`; the proxy only defines `_proxy_parent`. Every view call raises `AttributeError`. |
| `.emit()` / `EthSend` silently no-ops under gltest. | No `EthSend` branch in `wasi_mock`; the failure sentinel becomes `Lazy(lambda: None)` and `_generate_send` swallows it. **Worse than an error — it reports success.** |
| `genvm-linter` false positive on nested functions. | A `gl.nondet` call in a helper called from the leader function is flagged E010; sibling-nested call edges get the wrong scope. Workaround: inline the nondet call in the leader function. |
| Hosted networks reject `getContractSchemaForCode`. | genlayer-py ships a hosted-Studio client purely for schema lookup. |
| studio-dev is fee-charging. | Txs need a fee distribution + non-zero `feeValue`. No published Python SDK encodes that ABI; see `deploy/fees_aware.py`. |

## The two SDKs disagree about whether a live contract exists

Verified 2026-10-03, reproduced twice, same endpoint and same chain both times.

- `genlayer-py` 0.18.0 → `gen_call failed (code=-32001): Contract 0x37E08A26… not found`
- `genlayer-js` 1.1.8 → reads it, returns real verdicts (confirmed in production)

Ruled out as causes: wrong RPC (`genlayer_py.chains.studionet`'s endpoint is byte-identical to
`GENLAYER_STUDIO_RPC`), wrong chain (61999 both), missing contract (the JS client reads it), and
wrong address (the deployed app reads it through the same address).

**Never conclude "the contract is gone" from a Python SDK `gen_call` failure.** Cross-check with
`genlayer-js` or the deployed app before believing it. This is the same failure class as the
`emit()` no-ops: a call whose return value contradicts the target. Full detail in
`state/reviews/2026-10-03-vercel-deploy/DEPLOY-VERIFICATION.md`.

## Vercel: read `readyState`, not the CLI's exit code

`vercel deploy` reported `Error: fetch failed` on every attempt, including attempts that had
actually succeeded. The real state is only in the deployments API (`readyState` =
`READY` / `ERROR` / `BLOCKED`) or the `vercel ls` table. Two blockers hid behind that one useless
error message: a commit author Vercel could not resolve to a GitHub account, and a critical
Next.js advisory.

The commit author Vercel accepts is the **email on the Vercel account** (`oxunifyy` →
`akoladefatoki108@gmail.com`), not the GitHub noreply address. Those are different identities:
`unifyWeb3@users.noreply.github.com` resolved fine and was then rejected for lacking deploy
permission on the team.

Also: project-level `ssoProtection` was `all_except_custom_domains`, which puts a login wall in
front of every URL. A "public demo" needs it cleared per project. And `cordon.vercel.app` belongs
to an unrelated project — the real URL is `cordon-oxunify.vercel.app`.

## Anti-equivocation technique (the core of the design)

Leader and validators fetch independently, so only fields that are fixed for a given transaction
*forever* may cross the consensus boundary. Dropped: block number, gas, timestamps, raw logs,
raw bodies. Kept: input selector, event-topic counts, value band, log band, receipt status.
There is a test asserting byte-identical digests for the same tx with different block/gas.
