# R1 resolved: does `gl.evm.contract_interface(...).emit()` deliver a freeze?

**Answer: no. Tested 2026-10-02 on a real GenVM node against a live EVM target.**

This closes the one gap that touched the product's headline claim. It resolves negatively, and
the negative is well evidenced.

## Setup

| Component | Value |
|---|---|
| Target protocol | `HaltablePool.sol` deployed to Base Sepolia — `0xDF9Ba466540D2Fe4a62650f4d849231a2cb32b7B` |
| Probe contract | `contracts/probe_emit.py` on Studionet — `0x0B3E621F4CdC339A5a73eE33359409D622cf1e0E` |
| GenLayer tx | `0x822df1f98392099ea816e8698aee980f66d02b606ae87b1cedd4482975c8bb05` |
| Verdict path | `FINALIZED`, `MAJORITY_AGREE` |

The probe is separate from `emergency_halt.py` on purpose. The product only emits when consensus
returns `CONFIRMED_EXPLOIT`, and manufacturing an exploit verdict purely to exercise the
transport would be dishonest. The probe calls the identical emit path directly, so the transport
is tested without faking evidence.

## The result

```
GenLayer tx      : FINALIZED, MAJORITY_AGREE
probe traces     : EMIT_RETURNED
probe counts     : freeze=1 unfreeze=0
pool frozenUntil : 1790968071   <- UNCHANGED (the value from an earlier manual test)
pool isFrozen    : false
```

Every signal the contract can produce says success:

- consensus finalized and agreed,
- `emit().freeze(...)` returned without raising,
- the contract incremented its own `freeze_calls` to 1,
- it wrote `EMIT_RETURNED` to its trace string.

**And the target chain never received anything.** `frozenUntil` still holds the value from a
manual `cast` test hours earlier.

## Why this is not an encoding mistake

Three things were ruled out before concluding:

1. **ABI shape.** `Target.Write.freeze` is declared `def freeze(self, reason: str, until: u256, /)`
   — positional-only, which the SDK's generator requires — matching the target's
   `freeze(string calldata, uint256)`. Same declaration as the product contract.
2. **Ghost-contract registration.** `isGhostContract(0xDF9B…7B)` on the consensus main contract
   returns `true`. The target is already registered, so registration is not the missing step.
3. **Call site.** The emit sits in a plain `@gl.public.write` with no nondet block, which is the
   correct place — cross-contract and EVM ops are forbidden inside a nondet block, and messages
   are only emitted on finality.

## Why the local GLSim finding was not enough on its own

Under local GLSim the emit is a **verified silent no-op**: `gltest`'s WASI mock has no `EthSend`
branch, so `gl_call` returns a sentinel that `gl_call_generic` maps to `Lazy(lambda: None)`, and
`_generate_send` returns it **without raising**.

That is the trap. A local test asserting "the emit succeeded" would pass green and prove nothing.
The GLSim result and this Studionet result agree, but only the live test settles it: on a real
node the call is handled, returns normally, and still produces no delivery.

## Consequence for the product

The GenLayer side is verified: the verdict, the rationale, the evidence, the bounded window, and
the self-lifting expiry all work, and are covered by 38 hermetic tests plus live consensus runs.

The **last hop to the EVM target does not work**. So the product's honest position is:

- The verdict is on-chain, public, and appealable.
- The freeze **window** and its expiry are enforced in GenLayer storage.
- The **delivery** of the freeze to an EVM contract is off-chain, via a documented watcher.

That last point is a real cost, not a footnote. Whoever runs the watcher holds a key that can
freeze. What the architecture changes is that the key can no longer freeze *unbounded and
unaccountably* — the window comes from an adjudicated verdict, it is on the public record, and
the target lapses it on its own. That is a weaker claim than "consensus freezes your protocol",
and it is the claim the evidence supports.

## What was verified about the fallback

`deploy/freeze_watcher.py`, shipped as working code rather than a documented intention:

- **Read path, live:** polled the deployed contract and correctly found all 3 cases, correctly
  deciding no action for each (none are `CONFIRMED_EXPLOIT`).
- **Write path, live:** invoked against the real target. `frozenUntil` moved, `isFrozen()`
  returned true, then returned false on expiry with **no unfreeze transaction sent**.

Only the *composition* — verdict observed → watcher fires — is unexercised, because no case has
reached `CONFIRMED_EXPLOIT` on live data. Both halves are proven; the joint has not run.

Two implementation notes worth keeping:

- **Base is an OP-stack L2 and requires `gasPrice`** alongside EIP-1559 fields. Omitting it fails
  with `Transaction must include these fields: {'gasPrice'}`.
- **Base Sepolia's clock runs ahead of the host** (~53s when measured). A deadline computed from
  the host clock produced a freeze whose `until` was already in the past, so `freeze()` silently
  reverted and `isFrozen()` stayed false. Read chain time, not `date +%s`.
