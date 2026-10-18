# Memory — durable decisions and constraints

Updated 2026-10-17.

## Stage 4 — live redeployment onto fresh keys, DONE (2026-10-17)

Everything below was observed, not planned.

| Role | Address |
|---|---|
| attester (signs verdicts; pool constructor arg) | `0x5627F3629aE04D9F34Ac6bC75d3FC16d4cD62f17` |
| GenLayer deployer (owner of the new IC) | `0x7b1860d29ba5d934cb80e35f4418B5a418a90E68` |
| Base Sepolia deployer **and** relay gas payer (also the pool's `owner`) | `0x4f198Dcda2376eCD9C9FF429662b6EA9Db5264fc` |

**New Intelligent Contract on Studionet 61999** —
`0x95be4d883F89F28CF9cE986e1B400c8CB0808201`, deploy tx
`0x32a2496298161e5cdb4660bd7c18be4ab37fb176610908ce3ee0fcb4d9e2da1a`.
Read back from the node rather than from the deploy script, whose output was lost (see the first
landmine below): `gen_getTransactionStatus` → `FINALIZED`; `gen_getContractSchema` → 11 methods;
keyless `gen_call` `stats()` → `{"cases": 0, "default_freeze_seconds": 3600,
"evidence_url_template": "", "freezes": 0, "owner": "0x7b18…0E68", "submits": 0}`; `list_cases()`
→ `[]`. Constructor args sent: `[owner=<GenLayer deployer>, "", "jsonrpc", <Base Sepolia public
RPC>]`. No view exposes `evidence_mode` or `evidence_rpc_url`, so they stay read-side unverified
until the first `submit_proof` in the live run.

Funded via the Studio's own `sim_fundAccount(address, 10**18)`: result
`0xf3d18644…048e126c`, and `eth_getBalance` moved `0` → `1e18` wei. `genlayer_py.fund_account()`
refuses any chain but localnet, so the method has to be called directly.

**Keys.** `/root/cordon/.env`, mode 600, covered by `.gitignore:2`, untracked — confirmed with
`git check-ignore -v .env` and an empty `git status --short`. Names only: `GENLAYER_PRIVATE_KEY`,
`CORDON_ATTESTER_PRIVATE_KEY`, `CORDON_ATTESTER_ADDRESS`, `BASE_SEPOLIA_PRIVATE_KEY`,
`BASE_SEPOLIA_RPC_URL`. Throwaway, testnet only, never printed, logged or committed.

**Target pool — Base Sepolia 84532: `0x9e6c83C8ea2b6d15aBe38105484FDCD6BA91300e`**, tx
`0x3a8f160e83aceb15ae2ea862d7457ab1c1587bfa49f3ca84ef758016fde1cba3`, block `0x2e03c61`,
gasUsed 1,116,751 (tx at ~0.006 gwei), replacing `0xDF9Ba466540D2Fe4a62650f4d849231a2cb32b7B`.
Constructor `attesters_ = [0x5627…2f17]`, `maxWindow_ = 3600`. It was deployed by the new
`deploy/deploy_target.py` — there was no way to send a creation transaction from this repo before
this stage. **Every constructor-set value and the interface were read back off the chain, not taken
from the receipt — 15/15 checks:** runtime code 4,646 bytes (the same length as the in-process EVM
deployment of the same artifact), the required selectors present (`freezeFromAttestation`,
`isAttester(address)`, `isFrozen()`, `unfreeze(string)`, `MAX_WINDOW()`), `freeze(string,uint256)`
absent, `isAttester(attester)` true, `isAttester(0x0)` false, `attesterCount() == 1`,
`MAX_WINDOW() == 3600`, `frozenUntil() == 0`, `isFrozen() == false`, `owner()` == the deployer,
`attestationDigest(…)` returns 32 bytes.

**`genlayer-py` reads the new contract.** 0.18.0 reported `not found` (`gen_call failed
(code=-32001)`) for `0x37E08A26…` — reproduced twice, at the correct endpoint, chain and address,
while `genlayer-js` read the same contract — and it does **not** reproduce against `0x95be4d88…`:
same SDK version, `gen_getContractSchema` → 11 methods, `read_contract("stats")` → the same dict the
keyless reader returns. So that failure was specific to the earlier deployment, not to the endpoint
or to the SDK as a whole. The keyless reader stays for the structural reason: `read_contract` raises
without a connected account, i.e. a GenLayer private key.

**Live run, 2026-10-17 (observed, nothing inferred).** Case `live-drain-run3`: a real `deposit()` of
0.0001 ETH into the new pool (`0xd7a4c3ad…3f67`, status `0x1`, block 48250491), submitted with
`--target 0x9e6c83C8…` so the record names the live pool. GenLayer tx `0xa249af99…4428b` →
`FINALIZED`, `MAJORITY_AGREE`, verdict **`FALSE_REPORT`**, evidence `found=True status=0x1
value=SMALL logs=FEW … to=0x9e6c83c8…`. `deploy/attest.py --case live-drain-run3` **refused**
(exit 3): `verdict is 'FALSE_REPORT', not CONFIRMED_EXPLOIT`, so nothing was signed and nothing was
frozen. There is still no live `CONFIRMED_EXPLOIT` and none was manufactured — the freeze path
stays covered by the hermetic suite, not by a live freeze.

What *was* shown live on Base Sepolia, without signing a false verdict:

- The deployed pool's `attestationDigest(...)` equals `deploy/attestation.py`'s digest for the same
  inputs (`0xee6d4225…`, chain ts 1792269740, `expiresAt +900`) — contract and signer agree byte for
  byte, on the live chain, not only in tests.
- `freezeFromAttestation` with a **valid signature from a key that is not the attester** reverted
  `unknown attester` in simulation and was broadcast and mined with **status `0x0`**
  (`0x51691169…d818`, block 48250749, 31,029 gas). `frozenUntil()` and `isFrozen()` were still
  `0`/`false` at that block and at `latest`. `isAttester(throwaway)` → 0, `attesterCount()` → 1.
- `node web/scripts/verify-live.mjs` (default case now `live-drain-run3`) exits 0 against the new
  contract: `evidence mode jsonrpc`, `value band SMALL`, `log band FEW`, `validator agreed true`,
  `rationale 255 chars`, `verdict FALSE_REPORT`, `is_frozen() agrees false`. The first line also
  closes the note above: `get_evidence` does report `evidence_mode: jsonrpc` — it is simply not in a
  view.

**App ids after the redeploy.** `sample-run.json` is a dated transcript (provenance: the *previous*
contract, 2026-10-02) and was deliberately not rewritten — those GenLayer tx ids are real
transactions on that contract, so editing the address inside it would falsify a record. Its ids
(`…-run2`) are therefore read only by the replay components. The case the page tracks **live**
(`web/src/app/page.tsx::DEFAULT_CASE`) and the verifier's default are `live-drain-run3`, the case
that exists on the current contract. Same split in `deploy/record_run.py`, whose `HALT` now points
at the new contract: re-running it writes a *fresh* transcript and replaces the old one.

**The funding gap, for the record.** The deployer balance was `0` on two separate reports (one
`eth_getBalance` each, HTTP 200, `0x0`) and the user's "funded" preceded the ETH. On the third read
it was `99991562780006198` wei — 0.1 ETH minus the funder's fee, which is *not* a sign that
anything was sent from the key: `eth_getTransactionCount` was `0x0` on both `latest` and `pending`.
One `eth_getBalance` per report, no polling, no faucet automation.

Landmines found in this stage, all new:

- **The test stub's receipt was snake_case; a node's is camelCase.** `eth-tester` hands back
  `contract_address`, so the stub re-emitted that and `deploy/deploy_target.py` — which reads
  `contractAddress`, correctly — hit "receipt reports success but has no contractAddress". The
  translation belongs in the stub, not the client: a client that read `contract_address` would be
  wrong against every real chain and would only find out live. `rpc_stub.py` now maps the standard
  receipt keys, and the same pass added the missing `eth_gasPrice` / `eth_getCode` (the relay never
  asked for them; the deployer does). `eth_gasPrice` returns the latest block's `base_fee_per_gas`
  rather than an invented number, because py-evm rejects a legacy transaction priced below the base
  fee — "Sender's max fee per gas (0) is lower than block's base fee per gas (875000000)".
- **`eth-abi` takes `bytes` for `bytes32`, but a hex string for `address`.** Passing a hex string
  for `bytes32` fails inside the encoder with a message naming the *value*, not the argument.
- **A receipt can be visible before `eth_call … "latest"` sees its effect.** Immediately after the
  deposit's receipt came back, a read of `deposits(deployer)` returned `0` while a read of the
  pool's *balance*, in the same second, returned `1e14`. Both are plain state reads of the same
  contract. A public load-balanced RPC can serve consecutive requests from nodes at different
  heads, so a read taken right after a receipt can legitimately describe the pre-transaction state.
  Pinned to the receipt's own block, the mapping reads `1e14`, and the block before it reads `0`.
  Any read that must be final should name the block, not `"latest"`.
- **The pool's attester accessor is `isAttester(address)`, not `attesters(address)`.** Assumed from
  the constructor parameter name; the structural selector check said `false` and the `eth_call`
  reverted. The same check says `true` for `isAttester(address)` and `freezeFromAttestation(...)`
  and `false` for `freeze(string,uint256)` — which is what makes the structural check worth having.

- **A killed deploy script is not a failed deploy.** `timeout 280` killed
  `deploy/deploy_studio_dev.py` (exit 124) *after* its transaction was submitted, and that
  transaction finalized. The script prints the tx id only at the very end, and
  `eth_getBlockByNumber` on Studionet is a stub (zero hashes, no transactions) so the chain cannot
  be scanned for it. Recovery: `explorer-studio.genlayer.com/address/<deployer>` lists type, status
  and `to` for the account — the contract address was read from there and then confirmed against
  the node. Run deploy scripts unbuffered (`python -u`), and treat exit 124 as "unknown", not
  "failed".
- **`.venv-deploy` does not exist in a fresh checkout and its dependency set is recorded nowhere.**
  Rebuild with `uv venv .venv-deploy --python 3.12 && uv pip install --python
  .venv-deploy/bin/python genlayer-py==0.18.0 requests python-dotenv`. `requests` and
  `python-dotenv` are imported by the deploy scripts but are not dependencies of `genlayer-py`.

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
- **`genvm-lint check` fails validation with a 404 unless `GENVMROOT` is set.** Verified
  2026-10-17 against `genvm-linter` 0.10.0. `genvm_linter/validate/artifacts.py` builds
  `.../releases/download/{latest}/genvm-universal.tar.xz` — it resolves the **latest** tag and
  never consults the contract's `Depends` pin. The latest tag is now `v0.3.0-rc7`, where that
  asset 404s because upstream renamed it to `genvm-runners-all.tar.xz` (HTTP 200 on the same
  tag). The old name still resolves on `v0.2.16`, so the contract's pin is fine; the tool is
  broken. Facts worth keeping straight:
  - The `download -v <tag>` subcommand accepts a version, but `check`/`validate` call
    `download_artifacts(version=None)`, so caching an older release does not help.
  - Do **not** fabricate a file named after the latest tag — a validation result attributed to
    a release that does not contain it is worthless.
  - Supported path: `sdk_loader.get_sdk_paths_from_genvmroot()` honours `$GENVMROOT`, expecting
    `<root>/runners/py-lib-genlayer-std/src`. Point it at the std lib `gltest` already extracted
    under `~/.cache/gltest-direct/extracted/<ver>/py-lib-genlayer-std/<hash>/` and both lint and
    validation pass. Confirm the pairing is real rather than assuming it: the pinned
    `py-genlayer` runner's own `runner.json` names its `py-lib-genlayer-std` hash. For this
    contract they match (`1jb45aa8…` → `11rhn002…`).
  - `genvm-linter`'s own cache lives at `~/.cache/genvm-linter`, separate from gltest's.

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

## Timestamp parsing: the zone is not part of the fraction (fixed 2026-10-17)

`contracts/emergency_halt.py::_strip_us` used to do `text.split(".", 1)[0]`, i.e. it discarded
*everything* after the dot. Right for `2026-10-17T09:00:00.123Z` (truncation), wrong for
`2026-10-17T09:00:00.123+02:00`: the offset goes with the fraction, `"+" in head` was then False,
`Z` was appended, and the instant silently moved by two hours. Only the run of digits directly
after the dot is sub-second precision — anything after those digits is the zone and now survives.
`deploy/attestation.py::iso_to_epoch` uses the same rule, because the attester *signs* the value it
returns, and a two-hour shift there is a signed deadline the record does not mean.

Two things this exposed, both fixed in the same commit:

- **Anything that orders these strings must fold the zone in first.** `_iso_le` compared stripped
  strings as text; `...10:00:00+02:00` is 08:00Z, which is after `...07:30:00Z`, but sorts before
  it. `_iso_key` now normalises to UTC via `_iso_shift(stripped, 0)` before comparing, and raises
  on unparseable input instead of comparing garbage as text. Every `expires_at` already ends in
  `Z` (`_iso_shift` emits nothing else), so the `Z`-against-`Z` path is byte-identical to before.
- The divergence test became an agreement test. The lesson to keep: when one implementation
  refuses a shape the other mis-reads, that is a *stopgap*, not a fix — a review that leaves it
  there should say "temporary" out loud.

Evidence: `tests/direct/test_relay_attestation.py -k "timestamp_shape or follows_the_fraction or
zone_and_drops or orders_by_instant"`. The old behaviour is pinned as wrong:
`_epoch("...09:00:00.123+02:00") != iso_to_epoch("...09:00:00Z")`.

Still true, and now the *only* shape both sides refuse (loudly, not silently): a zone written with
a minus, e.g. `...09:00:00.123-05:00`. Neither implementation recognises `-` as a zone marker — the
rule is `endswith("Z") or "+" in head` — so both append a `Z` and then fail to parse. Nothing in
the pipeline emits one; if a node ever does, it fails loudly on both sides rather than disagreeing.

## A refusal path that raises is not a refusal path

Found by reviewing the freeze diff, fixed 2026-10-17. `deploy/freeze_watcher.py::verify` promised
`RefusedToBroadcast` but called `normalize_address`, which raises `ValueError` on a malformed
string — and `main` only handles `RefusedToBroadcast`. So a junk `signer` field in the attestation
file (an operator-supplied file, i.e. untrusted input) escaped as a traceback: the relay said "this
tool is broken" where the truth was "this attestation is invalid". `deploy/attest.py::refusal_reason`
had the mirror-image version, comparing targets as raw strings so a malformed one passed the gate
and blew up later in `attestation_digest`. Rule: at every boundary, parse the untrusted value and
convert the parse failure into the refusal the caller already handles. Tests:
`test_verify_refuses_a_malformed_address_in_the_attestation_file`,
`test_build_attestation_refuses_a_malformed_target_instead_of_raising`.

Two related traps in the same path, both now pinned by tests:

- `requests.exceptions.JSONDecodeError` inherits from **both** `ValueError` and `RequestException`,
  so the transport branch swallows it and reports a bad body as a network fault. Catch it first —
  this was fixed once in `genlayer_read.py` and was still standing in `freeze_watcher.py::Evm._call`.
- An HTTP error *status* is not an empty result. A 502 from a proxy arrives as JSON with no
  `result`; without a status check that reads as "the contract answered nothing", sending the
  operator to debug the wrong layer.

Also: source-audit tests are the only way to prove an *absence* (no owner pause, no writer of
`frozenUntil`, no signing in the relay). `test_the_only_writers_of_frozenUntil_are_the_attested_
_path_and_unfreeze` parses the Solidity and enumerates every assignment; a behavioural test can
only cover the calls someone thought of.
