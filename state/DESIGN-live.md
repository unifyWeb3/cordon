# Design — an honest live `CONFIRMED_EXPLOIT` on a direct transaction

Written 2026-10-20, after the run in `docs/live-run-2026-10-20.md` showed that `HaltablePool`
cannot produce one. This note is the reasoning behind `demo-target/src/VulnerableDemoPool.sol`.

## 1. What the verdict rule actually is

`contracts/emergency_halt.py` has **no numeric threshold** for `CONFIRMED_EXPLOIT`. The model is
asked to choose between three strings, and the only definition is:

> `CONFIRMED_EXPLOIT` — the observed evidence supports an unauthorised drain or theft.

So the rule is: *the evidence, as rendered in the prompt, must support an unauthorised drain*. The
adjudicator is not counting bands; it is reading a summary. What it can read is exactly this, and
nothing else:

| Prompt row | Source | Moves with |
|---|---|---|
| `transaction_found` | receipt exists | — |
| `receipt_status` / `executed_successfully` | receipt status | — |
| `value_magnitude_band` | **the transaction's own `msg.value`** | ZERO ≤0, SMALL ≤1e18, MEDIUM ≤1e22, LARGE above |
| `log_count_band` | number of logs | NONE 0, FEW ≤2, SOME ≤8, MANY ≤32 |
| `transaction_to_address` | `tx.to` | — |
| `function_selectors_seen` / `event_signatures_seen` | **topic0 of every log** | — |
| `function_selector_called` | tx input selector | — |
| `event_signatures_repeated_within_this_tx` | topics appearing more than once | — |

The digest carries **no balance, no amount transferred, no caller identity, no storage reads**. That
is the hard constraint every design below has to respect.

Two gates sit between a verdict and a freeze, and both are deliberate:

1. `_record` downgrades `CONFIRMED_EXPLOIT` to `INSUFFICIENT_EVIDENCE` when
   `evidence.tx_to != target`. A confirmation about a transaction that never called the named pool
   is not evidence about that pool.
2. `deploy/attest.py` refuses to sign anything that is not a *finalized* `CONFIRMED_EXPLOIT` in
   `jsonrpc` mode whose record `target` **and** fetched `tx_to` both equal the pool being attested.

## 2. Why `HaltablePool` cannot reach it

* `withdraw(amount)` is not payable, so the transaction's own `value_band` is always `ZERO`.
* A transaction to the pool executes exactly one function, and `HaltablePool` emits exactly one
  event per successful call (`Deposited`, `Withdrawn`, `Frozen`, `Unfrozen`). So `log_band ≤ FEW`
  and `repeated_selectors` is **empty for every binding-valid transaction**.
* The only complete drain it permits is the sole depositor withdrawing its own credit — which the
  digest cannot distinguish from an ordinary withdrawal. Observed live: `FALSE_REPORT`, rationale
  “ZERO value magnitude band … no significant ETH transfer”.
* A receipt that *does* carry repeated events necessarily has `tx_to` elsewhere (a forwarding
  contract), so gate 1 rejects it. Observed live: `INSUFFICIENT_EVIDENCE` on `control-wrong-to`.

## 3. What a direct transaction must therefore look like

To satisfy both gates the exploit transaction must be **sent to the target pool** and must, in the
same transaction, produce evidence that reads as an unauthorised drain:

* `tx_to == target` — required, not negotiable.
* `executed_successfully = true`.
* `value_band > ZERO` — helps: the caller puts *something* in and the evidence shows value on the
  call. `SMALL` is reachable; `MEDIUM` would need 1,000 ETH.
* `log_band ≥ SOME` and, above all, `repeated_selectors` non-empty — the product's own
  documentation calls the repeated event topic “the drain signature”. `MANY` (9–32 logs) needs the
  target to emit ≥ 9 logs in one call.
* a claim whose mechanism is consistent with those rows.

The smallest shape that satisfies all of them: **a payable function on the target that pays
`msg.sender` in a loop, several times, from the pool's balance, emitting one identical event per
payout.** The loop is what produces `MANY` + `repeated_selectors`; being payable is what moves
`value_band` off `ZERO`; `tx_to == pool` is automatic.

## 4. The bug (deliberately planted, not simulated)

`VulnerableDemoPool.claimRewards(uint256 rounds)` is payable and, per round, pays
`address(this).balance / rounds` to `msg.sender`, emitting `Withdrawn(msg.sender, slice)`.

The accounting error is one line: the budget is taken from **the pool's whole balance** instead of
`deposits[msg.sender]`, and nothing is deducted from the caller's credit. A caller with **zero
deposit** therefore takes another depositor's ETH, in one transaction, in `rounds` payouts. The
contract's `deposit`/`withdraw` remain credit-capped, so the flaw is isolated to `claimRewards`.

Design choices, all for legibility of the receipt:

* the last payout is trimmed to whatever is left, so the pool ends at dust rather than stranded;
* `rounds` is capped at 16 and each round emits one log, so `12` rounds → `log_band = MANY`;
* the event is the pool's existing `Withdrawn`, whose topic is recognisable and truthfully describes
  “funds left the pool to this address”;
* the freeze check is on `claimRewards` too, so a freeze actually protects the flawed path.

## 5. What this design does **not** do

* It does not change the IC, its prompt, its enum or the target binding.
* It does not touch `HaltablePool.sol`; that contract stays the non-vulnerable demo.
* It does not make the verdict. Consensus does, over the real receipt, with the honest claim. If the
  model returns `FALSE_REPORT` or `INSUFFICIENT_EVIDENCE`, the run stops and the rationale is
  reported — the claim is not reworded until it passes.
* It does not hide what it is: the contract header says INTENTIONALLY VULNERABLE, the case id and
  claim say “staged”, and the transcript says the funds were ours on a testnet. The exploit is real;
  the victim is not.

## 6. Residual risk

The digest still cannot show the *amount* taken, so a strict adjudicator may refuse on the grounds
that the claim asserts more than the evidence measures. That is a legitimate verdict and is treated
as a result. The durable fix is an IC change (e.g. binding on a log emitted by the target, or
including the target's balance delta in the digest) — proposed, not implemented, until approved.

## 7. Outcome — live, 2026-10-20

This design was executed on the first live attempt. `claimRewards(12)` paid a zero-deposit caller
39,999,999,999,996 wei of another depositor's 40,000,000,000,000 wei in one transaction; the digest
was `value=SMALL logs=MANY rep=0x7084f547…` with `tx_to` equal to the pool; consensus returned a
finalized `CONFIRMED_EXPLOIT`; the attester signed; the relay landed the freeze; and `frozenUntil`
read back at the relay block equals the signed deadline.

The residual risk in §6 did not disappear — it was resolved by the adjudicator, not by the evidence.
The stored rationale says the behaviour is consistent with the loop drain, then: *"Even though the
claim labels this a 'staged test,' the on-chain behavior (MANY logs, repeated identical event,
successful execution draining funds…"* The model weighed the label and confirmed anyway. That is a
judgement call, and a different model could have made the other one; the hermetic suite is what
pins the contract-side rules.

Full hashes and re-verification: `docs/live-run-2026-10-20-confirmed.md`.
