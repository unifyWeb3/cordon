// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * INTENTIONALLY VULNERABLE — TESTNET ONLY. NEVER DEPLOY THIS TO A NETWORK THAT HOLDS VALUE.
 *
 * Why this contract exists
 * ------------------------
 * `HaltablePool` cannot produce a live CONFIRMED_EXPLOIT honestly, and the reason is structural:
 * its only outflow is not payable (so the transaction's own value band is ZERO), it emits one
 * event per call (so `repeated_selectors` is empty), and the adjudicator's target binding requires
 * the exploit transaction to be sent to the pool itself (so a forwarding contract cannot be the
 * exploit path). That was observed live on 2026-10-20; see `docs/live-run-2026-10-20.md`.
 *
 * This contract is the smallest honest target that *can* be exploited in one direct transaction:
 * it keeps the same attested-freeze interface as `HaltablePool`, and it adds one deliberately
 * flawed function that pays the caller from the pool's own balance in a loop. The result is a
 * receipt that a human can read as a drain and that the digest can describe: value on the call,
 * MANY logs, and one repeated event topic.
 *
 * The flaw (see `claimRewards`): the reward budget is `address(this).balance`, not
 * `deposits[msg.sender]`, and nothing is deducted from the caller's credit. Any address, with no
 * deposit at all, can take every depositor's ETH in a single transaction. The credit-capped
 * `deposit`/`withdraw` pair is correct, so the bug is isolated and testable.
 *
 * Everything below the accounting section is the same attested-freeze design as `HaltablePool`
 * (own copy on purpose: the deliverable and the demo target must not be edited for a test run).
 * `DOMAIN_SEPARATOR` binds this deployment's own address, so an attestation minted for any other
 * pool — including `HaltablePool` — cannot verify here.
 */
contract VulnerableDemoPool {
    // ------------------------------------------------------------------ freeze state

    /// notice Withdrawal freeze deadline as a unix timestamp. 0 == not frozen.
    uint256 public frozenUntil;

    string public freezeReason;
    bytes32 public freezeCaseId;
    address public freezeAttester;

    // ------------------------------------------------------------------ authority

    address public owner;

    /// notice Constructor-set attester set. No setter, ever.
    mapping(address => bool) private attesterSet;
    uint256 public immutable attesterCount;

    /// notice Longest freeze this pool will accept, in seconds. Constructor-set, no setter.
    uint256 public immutable MAX_WINDOW;

    // ------------------------------------------------------------------ attestation

    bytes32 public constant VERDICT_CONFIRMED_EXPLOIT = keccak256("CONFIRMED_EXPLOIT");
    bytes32 public constant ATTESTATION_TYPEHASH = keccak256(
        "Attestation(bytes32 caseId,address target,bytes32 verdictHash,bool finalized,uint256 expiresAt)"
    );

    bytes32 private constant _EIP712DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );

    bytes32 private immutable DOMAIN_SEPARATOR;

    event Deposited(address indexed who, uint256 amount);
    event Withdrawn(address indexed who, uint256 amount);
    event Frozen(bytes32 indexed caseId, address indexed attester, string reason, uint256 until);
    event Unfrozen(string reason);

    constructor(address[] memory attesters_, uint256 maxWindow_) {
        require(attesters_.length > 0, "no attesters");
        require(maxWindow_ > 0, "zero window");

        owner = msg.sender;
        MAX_WINDOW = maxWindow_;

        for (uint256 i = 0; i < attesters_.length; i++) {
            require(attesters_[i] != address(0), "zero attester");
            attesterSet[attesters_[i]] = true;
        }
        attesterCount = attesters_.length;

        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                _EIP712DOMAIN_TYPEHASH,
                keccak256("CordonVerdictAttestation"),
                keccak256("1"),
                block.chainid,
                address(this)
            )
        );
    }

    // ------------------------------------------------------------------ demo accounting

    mapping(address => uint256) public deposits;
    mapping(address => uint256) public withdrawals;

    function deposit() external payable {
        require(!isFrozen(), "paused");
        deposits[msg.sender] += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    /// notice The correct path: pays only the caller's own credit.
    function withdraw(uint256 amount) external {
        require(!isFrozen(), "paused");
        require(deposits[msg.sender] >= amount, "insufficient deposit");
        deposits[msg.sender] -= amount;
        withdrawals[msg.sender] += amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        emit Withdrawn(msg.sender, amount);
    }

    /**
     * @notice THE INTENTIONAL BUG. Pays the caller a share of the pool's whole balance, `rounds`
     *         times, without checking or deducting the caller's credit.
     * @dev The corrected version would take `budget = deposits[msg.sender]`, deduct it before the
     *      external calls, and pay `budget / rounds` per round. This one takes
     *      `address(this).balance`, so a caller with zero deposit receives other depositors' ETH.
     *      The loop exists so the shortfall is visible in the receipt as repeated payouts rather
     *      than as a single anonymous transfer.
     * @param rounds How many equal payouts to make. Capped at 16 to keep the receipt small.
     */
    function claimRewards(uint256 rounds) external payable {
        require(!isFrozen(), "paused");
        require(rounds > 0 && rounds <= 16, "rounds out of range");

        uint256 slice = address(this).balance / rounds;
        require(slice > 0, "nothing to claim");

        for (uint256 i = 0; i < rounds; i++) {
            (bool ok,) = msg.sender.call{value: slice}("");
            require(ok, "transfer failed");
            emit Withdrawn(msg.sender, slice);
        }
    }

    // ------------------------------------------------------------------ freeze interface

    /// notice True only while the deadline is in the future.
    function isFrozen() public view returns (bool) {
        return frozenUntil > block.timestamp;
    }

    function secondsUntilUnfreeze() external view returns (uint256) {
        if (!isFrozen()) return 0;
        return frozenUntil - block.timestamp;
    }

    function attestationDigest(
        bytes32 caseId,
        bytes32 verdictHash,
        bool finalized,
        uint256 expiresAt
    ) public view returns (bytes32) {
        return
            keccak256(
                abi.encodePacked(
                    bytes1(0x19),
                    bytes1(0x01),
                    DOMAIN_SEPARATOR,
                    ATTESTATION_TYPEHASH,
                    caseId,
                    address(this),
                    verdictHash,
                    finalized,
                    expiresAt
                )
            );
    }

    /// notice Permissionless: authority is the attester's signature, not msg.sender.
    function freezeFromAttestation(
        bytes32 caseId,
        bytes32 verdictHash,
        bool finalized,
        uint256 expiresAt,
        bytes calldata signature
    ) external {
        require(verdictHash == VERDICT_CONFIRMED_EXPLOIT, "verdict not confirmed");
        require(finalized, "verdict not finalized");

        address signer = _recover(
            attestationDigest(caseId, verdictHash, finalized, expiresAt),
            signature
        );
        require(signer != address(0) && attesterSet[signer], "unknown attester");

        require(expiresAt > block.timestamp, "window already closed");
        require(expiresAt <= block.timestamp + MAX_WINDOW, "expiry beyond max window");

        require(
            frozenUntil == 0 || frozenUntil <= block.timestamp || expiresAt <= frozenUntil,
            "cannot extend a live freeze"
        );

        frozenUntil = expiresAt;
        freezeCaseId = caseId;
        freezeAttester = signer;
        freezeReason = string(abi.encodePacked("cordon:", caseId));
        emit Frozen(caseId, signer, freezeReason, expiresAt);
    }

    /// notice Clear the freeze early. Owner-only, and it can only ever SHORTEN a window.
    function unfreeze(string calldata reason) external {
        require(msg.sender == owner, "not owner");
        frozenUntil = 0;
        freezeReason = "";
        freezeCaseId = bytes32(0);
        emit Unfrozen(reason);
    }

    function isAttester(address who) external view returns (bool) {
        return attesterSet[who];
    }

    // ------------------------------------------------------------------ ECDSA

    function _recover(bytes32 hash, bytes memory sig) internal pure returns (address) {
        if (sig.length != 65) return address(0);
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := mload(add(sig, 32))
            s := mload(add(sig, 64))
            v := byte(0, mload(add(sig, 96)))
        }
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            return address(0);
        }
        if (v != 27 && v != 28) return address(0);
        return ecrecover(hash, v, r, s);
    }
}
