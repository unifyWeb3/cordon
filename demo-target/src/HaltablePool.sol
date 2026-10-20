// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Demo target: a pausable withdrawal pool that accepts a freeze ONLY as a signed,
 * finalized CONFIRMED_EXPLOIT adjudication.
 *
 * Two properties matter, in this order.
 *
 * 1. The freeze is *attested*, not authorised. Anyone may call `freezeFromAttestation`,
 *    but the call only lands if an attester key signed a statement naming this pool,
 *    this verdict and this deadline. There is no owner pause path: `freeze(string,uint256)`
 *    is gone. The relay that carries the attestation holds no freeze authority at all.
 *
 * 2. The freeze is a *pure read of a deadline*, so it cannot outlive its window even if
 *    nobody sends an unfreeze transaction and even if the GenLayer contract disappears.
 *    That is what makes a wrong verdict cheap rather than dangerous.
 *
 * Why hand-rolled EIP-712 instead of a library: the encoder is small enough to read in
 * one sitting, and `attestationDigest` is public so the Python attester and this contract
 * can be asserted byte-identical in a test rather than trusted to agree.
 *
 * `abi.encodePacked` is used for the whole struct hash, so `bool finalized` occupies ONE
 * byte rather than a 32-byte word. The Python side must match that exactly; the
 * cross-language digest test is what catches a drift here.
 */
contract HaltablePool {
    // ------------------------------------------------------------------ freeze state

    /// notice Withdrawal freeze deadline as a unix timestamp. 0 == not frozen.
    uint256 public frozenUntil;

    string public freezeReason;
    bytes32 public freezeCaseId;
    address public freezeAttester;

    // ------------------------------------------------------------------ authority
    //
    // `owner` exists for the withdrawal accounting and for `unfreeze` (which can only
    // SHORTEN a window). It deliberately CANNOT pause. See freezeFromAttestation.

    address public owner;
    address public pendingOwner;

    /// notice Constructor-set attester set. There is intentionally NO setter for this:
    ///         the relay key is the owner, so an owner-settable attester set would let
    ///         the relay appoint itself and defeat the whole design.
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

    /**
     * @param attesters_  Addresses permitted to sign an attestation. Constructor-set and
     *                    final: there is no function that can change this set afterwards.
     * @param maxWindow_  Longest acceptable freeze window, in seconds.
     */
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

    function deposit() external payable {
        require(!isFrozen(), "paused");
        deposits[msg.sender] += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    mapping(address => uint256) public deposits;
    mapping(address => uint256) public withdrawals;

    function withdraw(uint256 amount) external {
        require(!isFrozen(), "paused");
        require(deposits[msg.sender] >= amount, "insufficient deposit");
        deposits[msg.sender] -= amount;
        withdrawals[msg.sender] += amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        emit Withdrawn(msg.sender, amount);
    }

    // ------------------------------------------------------------------ freeze interface

    /// notice True only while the deadline is in the future.
    /// dev Deliberately a pure read of the deadline. No human action, and no off-chain
    ///      process, is required for an expired freeze to stop blocking withdrawals.
    function isFrozen() public view returns (bool) {
        return frozenUntil > block.timestamp;
    }

    /// notice Seconds until the freeze lapses. 0 when not frozen.
    function secondsUntilUnfreeze() external view returns (uint256) {
        if (!isFrozen()) return 0;
        return frozenUntil - block.timestamp;
    }

    /// notice The EIP-712 digest an attester must sign. Public so the off-chain signer and
    ///         this contract can be asserted byte-identical in a test.
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

    /**
     * @notice Freeze this pool, if and only if an attester signed a statement saying it was.
     * @dev Permissionless by design: authority comes from the signature, not from msg.sender.
     *      The caller only pays gas. `target` is NOT a parameter -- it is baked into
     *      DOMAIN_SEPARATOR as `verifyingContract`, so an attestation minted for a different
     *      pool yields a digest this contract never signed; ecrecover then returns a
     *      meaningless address and the call fails with "unknown attester".
     */
    function freezeFromAttestation(
        bytes32 caseId,
        bytes32 verdictHash,
        bool finalized,
        uint256 expiresAt,
        bytes calldata signature
    ) external {
        // Verdict shape is checked first so a malformed request fails with a useful reason
        // rather than a generic signature error.
        require(verdictHash == VERDICT_CONFIRMED_EXPLOIT, "verdict not confirmed");
        require(finalized, "verdict not finalized");

        address signer = _recover(
            attestationDigest(caseId, verdictHash, finalized, expiresAt),
            signature
        );
        require(signer != address(0) && attesterSet[signer], "unknown attester");

        require(expiresAt > block.timestamp, "window already closed");
        require(expiresAt <= block.timestamp + MAX_WINDOW, "expiry beyond max window");

        // A live freeze may be re-applied at the same deadline or shortened, never extended.
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
    ///         This is deliberately not a pause authority: it cannot create a freeze.
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
        // Upper-half-order `s` is rejected outright: without this a signature has two
        // valid encodings and a replayed one would not reproduce the same address.
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            return address(0);
        }
        if (v != 27 && v != 28) return address(0);
        return ecrecover(hash, v, r, s);
    }

    // ------------------------------------------------------------------ ownership

    function transferOwnership(address to) external {
        require(msg.sender == owner, "not owner");
        require(to != address(0), "zero address");
        pendingOwner = to;
    }

    function acceptOwnership() external {
        require(msg.sender == pendingOwner, "not pending owner");
        owner = pendingOwner;
        pendingOwner = address(0);
    }
}