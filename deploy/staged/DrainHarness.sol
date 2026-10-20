// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * TEST HARNESS FOR THE STAGED DRAIN. NOT PART OF THE PRODUCT.
 *
 * Why this file exists, in full, so nobody has to guess later:
 *
 * `HaltablePool` holds ETH and has exactly one outflow, `withdraw(amount)`, which pays
 * `msg.sender` and is capped at `deposits[msg.sender]`. So the only complete drain its own
 * functions allow is "the sole depositor withdraws everything". When that is done from an EOA the
 * receipt is: one `Withdrawn` log, `value_band=ZERO` (a withdrawal sends no ETH itself), and the
 * `withdraw` selector. Adjudicated live on 2026-10-20 as case `staged-drain-plain`, that evidence
 * was judged FALSE_REPORT with the rationale "ZERO value magnitude band ... no significant ETH
 * transfer" — correct, because the digest measures the transaction's own `msg.value`, not the
 * value the call moved. An ETH drain therefore cannot appear in the digest at all.
 *
 * The digest's drain signal is `repeated_selectors`: the same event topic firing several times in
 * one transaction. This harness produces that signal *honestly*: it is the pool's depositor, it
 * withdraws its own deposit through the pool's real `withdraw`, and it then forwards the proceeds
 * to several sinks, emitting one `Swept` event per hop. Every log in the receipt is a real event
 * from a real call. Nothing here touches the pool's storage or bypasses a check.
 *
 * It is still not an exploit: the funds were the harness's own deposit. The claim submitted with
 * it says that, and the transcript labels the case as a staged test on our own testnet pool.
 */
interface IHaltablePool {
    function deposit() external payable;
    function withdraw(uint256 amount) external;
    function deposits(address who) external view returns (uint256);
}

contract DrainHarness {
    address public immutable pool;
    address[] public sinks;

    event Swept(address indexed sink, uint256 amount);

    constructor(address pool_, address[] memory sinks_) {
        require(pool_ != address(0), "no pool");
        require(sinks_.length > 0, "no sinks");
        pool = pool_;
        sinks = sinks_;
    }

    /// notice Deposit into the pool, credited to this contract.
    function deposit() external payable {
        IHaltablePool(pool).deposit{value: msg.value}();
    }

    /// notice Withdraw this contract's whole pool credit, then forward the proceeds to the sinks.
    ///         One transaction, so the pool's entire balance leaves in it. `msg.value` is added to
    ///         what is forwarded, which is why the transaction's own value band is not ZERO.
    function drain() external payable {
        uint256 credit = IHaltablePool(pool).deposits(address(this));
        require(credit > 0, "nothing to drain");
        IHaltablePool(pool).withdraw(credit);

        uint256 total = address(this).balance;
        uint256 share = total / sinks.length;
        for (uint256 i = 0; i < sinks.length; i++) {
            uint256 amount = i == sinks.length - 1 ? address(this).balance : share;
            (bool ok, ) = sinks[i].call{value: amount}("");
            require(ok, "sink refused");
            emit Swept(sinks[i], amount);
        }
    }

    receive() external payable {}
}
