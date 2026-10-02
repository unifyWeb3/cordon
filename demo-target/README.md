# Demo target — `HaltablePool.sol`

The EVM side of the demo: a pausable withdrawal pool that receives a freeze from the GenLayer
contract and lifts it on its own.

## Why it looks like this

One property matters more than anything else here:

```solidity
function isFrozen() public view returns (bool) {
    return frozenUntil > block.timestamp;
}
```

`isFrozen()` is a **pure read of a deadline**. A freeze cannot outlive its window even if no
unfreeze transaction is ever sent, and even if the GenLayer contract goes away entirely. That
is what makes a wrong verdict cheap rather than dangerous.

If you integrate this and compute `isFrozen()` any other way — a boolean that only a separate
call can clear — you have reintroduced exactly the failure mode this project exists to fix:
freeze state that depends on someone remembering to undo it.

## Interface the GenLayer contract calls

```solidity
function isFrozen() external view returns (bool);
function freeze(string calldata reason, uint256 until) external;
function unfreeze(string calldata reason) external;
```

`until` is a **unix timestamp in seconds**, matching `_epoch()` in
`contracts/emergency_halt.py`.

## Deploying

Needs `solc ^0.8.24` and foundry or hardhat. No test framework is vendored here.

```bash
# foundry
forge init --no-git --force .
cp ../demo-target/HaltablePool.sol src/
forge build
forge create src/HaltablePool.sol:HaltablePool --rpc-url "$RPC" --private-key "$PK" \
  --broadcast
```

## Exercising the freeze locally (no GenLayer involved)

```bash
# 1. deposit
cast send $POOL "deposit()" --value 1ether --rpc-url $RPC --private-key $PK

# 2. freeze for 60 seconds
cast send $POOL "freeze(string,uint256)" "manual test" \
  $(( $(date +%s) + 60 )) --rpc-url $RPC --private-key $PK

# 3. withdrawals now revert
cast send $POOL "withdraw(uint256)" 1000000000000000000 --rpc-url $RPC --private-key $PK
# -> revert: paused

cast call $POOL "isFrozen()(bool)" --rpc-url $RPC          # true
cast call $POOL "secondsUntilUnfreeze()(uint256)" --rpc-url $RPC

# 4. wait it out -- nobody does anything, and the freeze is gone
sleep 61
cast call $POOL "isFrozen()(bool)" --rpc-url $RPC          # false
cast send $POOL "withdraw(uint256)" 1000000000000000000 --rpc-url $RPC --private-key $PK  # succeeds
```

Step 4 is the whole thesis in five commands: **the failure mode self-heals.**

## Honest status

This contract is **not yet deployed**, so the last hop of the GenLayer freeze — EVM `emit()`
— remains unverified end to end. See "What we could not verify" in the top-level README. What
is verified is the freeze semantics on the EVM side (above, locally) and the GenLayer side
verdict/expiry logic (hermetic suite plus live consensus runs).
