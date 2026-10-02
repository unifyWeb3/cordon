/**
 * Every user-visible string and every number in the landing sections reads from here.
 * No literals in JSX.
 *
 * Two reasons. First, it makes the narrative checkable against README.md and the live transcripts
 * in one place. Second, it stops the page drifting away from what was actually measured --
 * a claim cannot quietly get stronger than the evidence if the claim lives in a file someone
 * reads next to the evidence.
 *
 * The emit caveat in `emit` is load-bearing. Phase 1 tested it and it does not work. This page
 * says so in the same words as the README; there is no softer version anywhere.
 */

export const product = {
	name: "Cordon",
	tagline: "Anyone can propose a freeze. Nobody performs one alone.",
	sub: "A GenLayer Intelligent Contract adjudicates exploit proofs against live chain evidence, " +
		"then issues a freeze that expires on its own. No human has to undo a mistake.",
} as const;

export const problem = {
	eyebrow: "The problem",
	lede: "Freeze authority is one unaccountable key. It is slow when it is needed, and it is " +
		"dangerous when it is used.",
	points: [
		{
			figure: "~46 min",
			what: "Kelp DAO's pauser multisig froze the protocol 46 minutes after a ~$292M drain.",
		},
		{
			figure: "30,766 ETH",
			what: "Aave is in SDNY fighting a freeze of 30,766 ETH (~$73M) applied to Arbitrum DAO.",
		},
		{
			figure: "the objection",
			what: "Michael Egorov, Curve: “The circuit breakers are controlled by humans, which " +
				"means they could become a potential vulnerability themselves.”",
		},
	],
	counterweight:
		"Consensus takes about a minute and does not beat 46 minutes. This is tier-2 judgement " +
		"for ambiguous cases — not a replacement for a deterministic tripwire. Pair it with one.",
} as const;

export const howItWorks = {
	eyebrow: "How it works",
	steps: [
		{
			n: "1",
			title: "Anyone proposes",
			body: "A target address, a transaction hash, one paragraph. Proposing a freeze is " +
				"permissionless; nobody can perform one unilaterally.",
		},
		{
			n: "2",
			title: "The contract reads the chain itself",
			body: "One batched JSON-RPC call to the protocol's own public RPC. No oracle, no " +
				"indexer, no API key, no hosting.",
		},
		{
			n: "3",
			title: "Only stable fields reach consensus",
			body: "Block number, gas and timestamps are dropped. What survives is fixed for a " +
				"given transaction forever — so leader and validators cannot disagree about the evidence.",
		},
		{
			n: "4",
			title: "Validators compare one enum",
			body: "Each re-runs the leader independently and compares the verdict only. Reasoning " +
				"is stored and never compared — two models never write the same sentence.",
		},
		{
			n: "5",
			title: "A freeze is bounded and self-lifting",
			body: "Confirmed exploits arm a freeze with a mandatory expiry. When the window " +
				"closes the target resumes, with no human action.",
		},
	],
} as const;

export const assurances = [
	{
		claim: "Every verdict names the evidence field that decided it",
		note: "Verdicts are checked against measured chain data, not a narrative.",
	},
	{
		claim: "The verdict enum is compared across validators; the reasoning never is",
		note: "Proved by a test: same enum with a completely different rationale still agrees.",
	},
	{
		claim: "A wrong freeze expires on its own — no human has to undo it",
		note: "Verified on a live chain: withdrawals reverted `paused`, then succeeded with " +
			"nothing sent.",
	},
] as const;

/**
 * The honest version of the transport, which is also the strong version.
 *
 * Do not upgrade this. `gl.evm.contract_interface(...).emit()` was tested against a live target
 * on 2026-10-02: consensus finalized with MAJORITY_AGREE, the call returned without raising,
 * the contract recorded the call — and the target chain received nothing. Delivery is done
 * off-chain by deploy/freeze_watcher.py.
 */
export const emit = {
	heading: "What the consensus does and does not do",
	does:
		"The verdict is decided on-chain by a validator committee, is publicly readable, and is " +
		"appealable. Anyone can re-run the reasoning and check it.",
	doesNot:
		"Delivering the freeze to your contract is off-chain. `emit()` was tested against a live " +
		"target and does not deliver: every signal the contract can produce says success while " +
		"the target chain receives nothing.",
	trade:
		"So the watcher needs a key that can freeze. What changes is that the key can no longer " +
		"freeze unbounded and unaccountably — the window comes from an adjudicated verdict, it is " +
		"on the public record, and the target lapses it itself.",
} as const;

export const limits = [
	"On random public transactions the correct answer is usually “not an exploit”. A pause " +
		"module that says yes to everything is the dangerous one.",
	"Judgement on borderline evidence is not deterministic. We saw one transaction rotate four " +
		"times and settle on the conservative verdict — at roughly 95s instead of 52s.",
	"No paying user. No protocol team has been asked whether they want this.",
] as const;

export const verdictBlurb: Record<string, string> = {
	CONFIRMED_EXPLOIT: "Evidence supports an unauthorised drain. A bounded freeze is armed.",
	FALSE_REPORT: "Ordinary activity. The evidence contradicted the claim, so nothing happened.",
	INSUFFICIENT_EVIDENCE: "Nothing conclusive. No action taken — the safe direction.",
};

/** The drain case: the strongest argument the product has, told with its real numbers. */
export const pivot = {
	headline: "A drain-shaped transaction, and the committee still would not confirm it.",
	body:
		"Fourteen repeated Transfer events in one transaction, `logs=MANY`, and a claim saying " +
		"swept the pool. The digest was byte-identical across two independent fetches. The first " +
		"run answered FALSE_REPORT. The second rotated four times and settled on " +
		"INSUFFICIENT_EVIDENCE. Both times, nothing was frozen.",
	note:
		"A disputed freeze becomes no freeze. That is the property that makes the cost of being " +
		"wrong bounded.",
} as const;

export const nav = {
	problem: "Problem",
	how: "How it works",
	live: "Live run",
	console: "Submit a proof",
	limits: "Limits",
} as const;
