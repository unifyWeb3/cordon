// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * Test-only corrected twin of `VulnerableDemoPool.claimRewards`.
 *
 * NOT DEPLOYED ANYWHERE AND NOT PART OF THE PRODUCT. It exists so the test suite can assert
 * the exact line that is wrong in the vulnerable pool: the budget. Here the budget is
 * `deposits[msg.sender]`, it is zeroed BEFORE the external calls, and a caller with no
 * deposit gets "nothing to claim". On the vulnerable pool the budget is
 * `address(this).balance`, which is how a zero-deposit caller takes everyone else's ETH.
 *
 * Deliberately minimal: no freeze logic, because the freeze path is exercised against the
 * vulnerable pool itself.
 */
contract FixedClaimPool {
    mapping(address => uint256) public deposits;

    event Withdrawn(address indexed who, uint256 amount);

    function deposit() external payable {
        deposits[msg.sender] += msg.value;
    }

    function claimRewards(uint256 rounds) external {
        require(rounds > 0 && rounds <= 16, "rounds out of range");
        uint256 slice = deposits[msg.sender] / rounds;
        require(slice > 0, "nothing to claim");

        // Effects before interactions, and only the caller's own credit.
        deposits[msg.sender] = 0;

        for (uint256 i = 0; i < rounds; i++) {
            (bool ok,) = msg.sender.call{value: slice}("");
            require(ok, "transfer failed");
            emit Withdrawn(msg.sender, slice);
        }
    }
}
