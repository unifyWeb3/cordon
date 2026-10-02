// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Demo target: a pausable withdrawal pool, and the receiver for a GenLayer freeze.
 *
 * The point of this contract is that `isFrozen()` is a pure function of the stored deadline.
 * A freeze cannot outlive its window even if nobody sends an unfreeze transaction, which is
 * what makes a *wrong* GenLayer verdict cheap.
 *
 * Deploy to any EVM testnet you like. The GenLayer contract only needs `isFrozen`, `freeze`
 * and `unfreeze`; everything else here is demo scaffolding.
 */
contract HaltablePool {
    address public owner;
    address public pendingOwner;

    /// notice Withdrawal freeze deadline as a unix timestamp. 0 == not frozen.
    uint256 public frozenUntil;

    string public freezeReason;

    mapping(address => uint256) public deposits;
    mapping(address => uint256) public withdrawals;

    event Deposited(address indexed who, uint256 amount);
    event Withdrawn(address indexed who, uint256 amount);
    event Frozen(string reason, uint256 until);
    event Unfrozen(string reason);

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    // ------------------------------------------------------------------ demo accounting

    function deposit() external payable {
        require(!isFrozen(), "paused");
        deposits[msg.sender] += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

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

    // ------------------------------------------------------------------ authority
    //
    // In the demo the deployer is the pause authority. In a real integration this would be
    // the same multisig that could freeze unilaterally today -- the point is that the freeze
    // now has a deadline nobody can extend, not that authority disappears.

    function freeze(string calldata reason, uint256 until) external onlyOwner {
        require(block.timestamp < until, "until must be in the future");
        frozenUntil = until;
        freezeReason = reason;
        emit Frozen(reason, until);
    }

    function unfreeze(string calldata reason) external onlyOwner {
        frozenUntil = 0;
        freezeReason = "";
        emit Unfrozen(reason);
    }

    function transferOwnership(address to) external onlyOwner {
        require(to != address(0), "zero address");
        pendingOwner = to;
    }

    function acceptOwnership() external {
        require(msg.sender == pendingOwner, "not pending owner");
        owner = pendingOwner;
        pendingOwner = address(0);
    }
}
