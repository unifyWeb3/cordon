# Submission notes

Drafted against the portal's required three-part instruction `[A6]`: **what it does**, **the problem
it solves**, and **how to use it**. Trim to taste, but keep the three headings — the form asks for
them.

Repo: <https://github.com/unifyWeb3/cordon> (public)
Live app: <https://cordon-oxunify.vercel.app>
Headline case: <https://cordon-oxunify.vercel.app/case/live-drain-run2>
Demo video: [`demo/cordon-demo.mp4`](demo/cordon-demo.mp4) — 41 s, silent

Not `cordon.vercel.app` — that subdomain belongs to an unrelated project called *Condor Gaming*.
Vercel subdomains are globally unique, so the short name was never available for this repo.

---

## What it does

**Cordon** is a GenLayer Intelligent Contract that adjudicates exploit reports against DeFi
protocols and issues a freeze that expires on its own.

Anyone can propose a freeze. Nobody performs one alone. The contract reads the referenced
transaction directly from the protocol's own public JSON-RPC endpoint — no oracle, no indexer, no
API key — reduces it to a set of **stable fields**, and asks a committee of validators for one
discrete verdict:

| Verdict | What happens to the target |
|---|---|
| `CONFIRMED_EXPLOIT` | A freeze is armed, with a **mandatory auto-expiry**. No human performs it. |
| `FALSE_REPORT` | Nothing happens. The evidence contradicted the claim. |
| `INSUFFICIENT_EVIDENCE` | Nothing happens. There is nothing unambiguous to judge. |

The result is a discrete enum, not a scalar risk score. A protocol cannot be "partially frozen".

The property that matters: **a wrong freeze lifts itself.** Freeze authority is time-boxed by
construction, so being wrong is bounded rather than permanent.

## The problem it solves

Today, freeze authority in DeFi is a single unaccountable privileged key. That is bad in both
directions, and both directions have cost real money:

- **Too slow.** Kelp DAO's pauser multisig froze a protocol 46 minutes after a ~$292M drain.
- **Too dangerous to use.** Aave is in SDNY fighting a freeze of 30,766 ETH (~$73M) applied to
  Arbitrum DAO.

The circuit breakers are controlled by humans, which the Curve founder Michael Egorov named as an
attack surface in itself: *"The circuit breakers are controlled by humans, which means they could
become a potential vulnerability themselves."*

A freeze that a single key can apply is a key worth attacking. A freeze that only a validator
committee can arm, whose expiry is enforced on-chain, removes both the single point of failure and
the incentive to hold the key.

Cordon is **not** a replacement for a deterministic tripwire. Consensus takes about a minute, so
it is tier-2 judgement for ambiguous cases. Pair it with one.

## How to use it

**Read the app — no setup, no wallet.** <https://cordon-oxunify.vercel.app> renders a real
adjudication recorded against the deployed contract on GenLayer Studionet (chain 61999), and every
case has a shareable link at `/case/<caseId>`.

**Run the tests.** The contract is hermetic — 38 tests, no network:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/direct -q
```

**Point it at your own protocol.** The integration path is documented in
[`docs/integration.md`](docs/integration.md): submit a proof with a target address, a transaction
hash, and a claim. The contract reads that transaction itself.

## What I want feedback on

- **Is the stable-field boundary right?** Block number, gas, timestamps, raw logs and raw bodies
  are dropped before consensus, because two honest nodes reading the same transaction must not
  disagree on the evidence. A test asserts byte-identical digests across differing blocks and gas.
  I would like a reviewer's opinion on whether that set is correct or over-narrow.
- **Is a discrete enum the right output shape** for an automated circuit breaker, versus a score
  with a threshold?
- **The freeze delivery hop is not what the brief assumed.** See below — this is the part most
  likely to be wrong.

## Honest limitations

Stated plainly, because a demo that overclaims is worse than one that does not:

1. **The contract cannot itself emit the freeze transaction.** `gl.evm.contract_interface(...).emit()`
   does not deliver — verified first under GLSim, then against a probe contract on Studionet, where
   it silently no-ops. The last hop is an off-chain watcher (`deploy/freeze_watcher.py`) that reads
   the armed state and sends the transaction. The watcher needs a key that can freeze, which is the
   exact trust property this project set out to remove. It narrows the problem; it does not solve it.
   Full write-up in the README under *Tested, and found broken*.

2. **Every live case so far is `FALSE_REPORT` or `INSUFFICIENT_EVIDENCE`.** That is the correct
   verdict for random public transactions, and the headline case is deliberately a drain-shaped
   transaction the committee still declined to confirm. There is **no** live `CONFIRMED_EXPLOIT` in
   the public record, so the freeze-arming path is covered by the hermetic suite and not by a live
   run. Manufacturing a fake drain to produce one would have been dishonest.

3. **Not deployed to studio-dev**, the brief's stated target. It is fee-charging and no published
   Python SDK encodes its ABI; every deploy returned `FINISHED_WITH_ERROR` with `num_of_rounds=0`,
   including a 20-line probe contract. The live deployment is on Studionet.

4. **Consensus is not a deterministic tripwire.** Roughly a minute, and validator rotation can
   change the answer: one recorded tx was re-run four times and rotated between `FALSE_REPORT` and
   `INSUFFICIENT_EVIDENCE` on a byte-identical digest. It settled toward the conservative verdict.
   Both times, nothing was frozen.

5. **A `genlayer-py` read defect is open and unfixed.** `genlayer-py` 0.18.0 reports
   `Contract 0x37E08A26… not found` for a contract that `genlayer-js` 1.1.8 reads successfully at
   the same endpoint on the same chain. Reproduced twice; endpoint, chain, address and existence
   all ruled out. This weakens the watcher's documented read path. The frontend claim is unaffected
   and was re-verified in production.