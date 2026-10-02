# Review finding — the frontend cannot currently read the deployed contract

Date: 2026-10-02. Reviewer: discovery session.
Severity: **blocker for M9 (demo) and for the rubric line "Frontend genuinely calls the contract".**
Found by the reviewer, not by the build session. Not a code defect in *your* code — an SDK version
defect that the pinned version walks straight into.

## What breaks

`web/package.json` pins `genlayer-js@2.0.0-rc.1`. Every read against the live contract fails:

```
readContract stats()       -> GenLayer RPC error (gen_call): execution failed
                             Missing or invalid parameters.
readContract list_cases()  -> same
readContract get_verdict() -> same
```

The UI will render empty or error on first load. Nobody has opened it, so this was never seen.

## Root cause (verified, not inferred)

The two SDKs disagree on the calldata frame key for the method name.

`genlayer-js@2.0.0-rc.1`, `node_modules/genlayer-js/dist/index.js:279`:

```js
function makeCalldataObject(method, args, kwargs) {
  let ret = {};
  if (method) {
    ret[""] = method;        // <-- EMPTY-STRING key
  }
  ...
```

`genlayer-py` (0.18.0, used by `deploy/`), `contracts/utils.py:10`:

```python
ret: Dict[str, CalldataEncodable] = {}
if method is not None:
    ret["method"] = method   # <-- "method" key
```

I captured the exact bytes each SDK sends for the identical logical call `stats()`:

| SDK | payload | node result |
|---|---|---|
| genlayer-py | `0xd08e0e06 6d6574686f6c 2c 7374617473 00` | **OK** |
| genlayer-js@2.0.0-rc.1 | `0xca88 0e00 2c 7374617473 00` | **ERROR** |

Decoded: the node expects `{"method": "stats"}` and gets `{"": "stats"}`. I confirmed the diagnosis by
hand-encoding the `method` key and calling `gen_call` directly — it returns the real payload
(`stats` → `{cases:3, freezes:0, submits:3, …}`). So the contract is fine, the network is fine, and the
2.0.0-rc.1 encoder is wrong for this RPC surface.

## The fix: downgrade to 1.1.8

`genlayer-js@1.1.8` (the current `latest` on npm — 2.0.0-rc.1 is a prerelease, and the discovery
brief already warned: *"For the Consensus v0.6 preview, install the explicit v2.0 release candidate …
Do not rely on the default npm tag to select a prerelease."* — the prerelease was installed
deliberately and is the wrong choice for `gen_call` reads on Studionet).

`1.1.8` uses `ret["method"]`. **Verified working against the live contract:**

```
stats OK: {"cases":3,"freezes":0,"submits":3,"owner":"0x3211d141…","default_freeze_seconds":3600,…}
list_cases OK: ["live-missing","live-real-tx","live-drain"]
get_verdict('live-drain') OK: "FALSE_REPORT"
```

One-line change in `web/package.json`, then reinstall.

## What the build session should check after downgrading

`readContract` is only half the path. **Re-verify the write path too**, since `2.0.0-rc.1` may have
changed other call shapes:

1. `readContract` for `stats`, `list_cases`, `get_verdict`, `get_evidence` — all four.
2. `writeContract` for `submit_proof` — the 1.1.8 write encoder is a different code path; do **not**
   assume it is fine because reads now work. A live submit costs a write but no weekly slot, so it
   is cheap to test.
3. The lifecycle poller (`PENDING → PROPOSING → COMMITTING → ACCEPTED → FINALIZED`) still advances.
4. `next build` still exits 0.

If `writeContract` in 1.1.8 turns out to encode writes the old 5-arg way the build session already hit
(`addTransaction`), that is a **second** blocker and the fallback is: keep 1.1.8 for reads and use the
already-working `deploy/submit_proof.py` (genlayer-py) for writes, proxying through a tiny local
route. That is worse than it sounds — it needs a server — so prefer testing 1.1.8 writes first.

## Why this matters for the score

Three rubric lines ride on this:

- *"Frontend genuinely calls the contract and handles the full transaction lifecycle"* `[A2]` — the
  lifecycle was verified through the **Python** client, not the browser. That is real evidence, but it
  is not the line as written.
- *"live demos… earn extra points and speed up review"* `[A2]` — an empty UI is worse than no UI.
- The self-review marked this line **Met** `[M0-RUBRIC-SELF-REVIEW.md:27]`. On the evidence now
  available, that verdict is **wrong** and should be downgraded to Met-pending-browser-check until
  someone loads the page against the live contract.

This is the "has anyone actually run it" gap in concrete form. The build session verified the
contract thoroughly and the frontend only statically. Both halves were necessary; they were never
joined.

## Also unverified while you are in there

- **`.env` is missing from `web/`.** Only `.env.example` exists, and it ships
  `NEXT_PUBLIC_HALT_ADDRESS=0x0000…0000`. The deployed address
  `0x37E08A2620495DC7C5A82Ef0CB8cDb5213aF774b` is not wired into the app, so even a correct SDK would
  read the zero address. Create `web/.env.local` from the example with the real address. It is
  public data, safe in a `NEXT_PUBLIC_*` var, and must stay out of git.