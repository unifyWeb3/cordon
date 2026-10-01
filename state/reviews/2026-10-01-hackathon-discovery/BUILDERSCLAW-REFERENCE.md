# Reference teardown — BuildersClaw (the 2000-pt Grand Winner)

Inspected 2026-10-01. This is the only GenLayer project I could actually read source for that won a
hackathon track, so it is the best available calibration for "what a high-scoring build looks like."
Everything below is from the repository itself unless marked as inference.

- Repo: `https://github.com/buildersclaw/buildersclaw` (TypeScript, monorepo `pnpm` workspaces)
  - `apps/api`, `apps/web`, `apps/worker`, `apps/contracts`, `apps/genlayer`; `packages/`, `docs/`, `scripts/`
  - `stargazers_count: 1`, `forks_count: 1`, **no license file**, created 2026-03-22, last push 2026-06-13
  - Runtime site `https://buildersclaw.xyz` + API `https://api.buildersclaw.xyz`
- Award: Bradbury Hackathon **Grand Winner**, **2000 pts**, portal highlight dated 2026-03-22/2026-04
  (`SOURCES.md` [B2], [B5])
- Read: `docs/GENLAYER.md` (163 lines), `apps/genlayer/contracts/hackathon_judge.py` (7.6 KB),
  `apps/genlayer/tests/integration/test_hackathon_judge.py`, `apps/genlayer/gltest.config.yaml`,
  `apps/genlayer/pyproject.toml`, `apps/genlayer/CLAUDE.md`

---

## 1. What they got for 2000 pts, stated by the organizer

> "a two-stage on-chain judging pipeline that replaces subjective panels with scalable, verifiable AI
> consensus, plus smart contracts that handle escrow and payouts end to end" — and "one of the most
> ambitious expressions of what Intelligent Contracts can unlock" `[B2]`

Three things are in that sentence that map onto rubric lines:
- **two-stage** → a real pipeline, not a single call
- **verifiable** → on-chain record
- **escrow and payouts end to end** → a completed money path, not a demo

## 2. The architecture decision that matters most

They did **not** put GenLayer in the hot path. From `docs/GENLAYER.md`:

> 1. Gemini scores every viable submission as the first broad repo/code filter.
> 2. The platform builds a transparent evidence score from peer agent reviews, AI repo/code judging,
>    and AI deployed URL runtime judging.
> 3. **The top contenders are sent to GenLayer for the final on-chain verdict.**

Their stated reason:

> "This keeps broad repo analysis fast, makes the finalist ranking explainable, and still gives
> GenLayer final say for the highest-stakes winner decision."

**This is the single most transferable lesson in this file, and it corrects my original plan.** My
`FINDINGS.md` had the contract fetching live data per submission, which puts consensus on the hot path
of every request and maximises the equivocation risk (R2). Their shape is the inverse: **cheap
deterministic work first, consensus only for the few decisions that are high-stakes and
irreversible.** Adopt it. It also answers the "not just a better LLM response" line by construction —
there is a measurable off-chain evidence layer that the on-chain verdict is accountable to.

Their finalist scoring weights, for reference: peer agent review 40%, AI repo/code judging 30%, AI
deployed-URL runtime judging 30%. Note the **30% for deployed-URL runtime evidence** — a grader
rewarded a submission that captured HTTP status, page title, visible text, screenshots, console
errors and failed network requests. *Our frontend demo should emit that evidence too.*

## 3. The consensus pattern — copy this shape

`hackathon_judge.py` is the reusable artifact. Key mechanics:

```python
verdict = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
```

- `leader_fn()` builds a prompt and calls `gl.nondet.exec_prompt(task, response_format="json")`
- `validator_fn(leader_result)` **independently re-runs `leader_fn()`** and compares only a
  **discrete field** (`winner_team_id` equality)
- Their comment: *"Only the winner_team_id must match — reasoning will differ. This is Partial Field
  Matching (Pattern 1 from GenLayer docs)."*

**This resolves my R2 equivocation worry for the decision step.** Free-text reasoning will never
match across different models; a small enum will. Design our contract the same way: `leader_fn`
returns `{"verdict": "CONFIRMED_EXPLOIT"|"FALSE_REPORT"|"INSUFFICIENT_EVIDENCE", "rationale": "..."}`
and `validator_fn` compares **only `verdict`**. The rationale is stored, never compared.

Other patterns worth copying verbatim:

| Pattern | Why it matters |
|---|---|
| `@allow_storage` on the `@dataclass` storage type | Required for `TreeMap`/dataclass persistence. A missing `@allow_storage` fails at storage-allocation time, not import time. |
| `_only_owner()` guard raising `gl.vm.UserError` | Cheap authorization on admin writes |
| `if self.result.finalized: raise` idempotency guard | Prevents double-finalize |
| **Copy storage into locals before defining nondet callbacks** — `title = self.title; brief = self.brief` | Their comment: *"GenVM nondet callbacks cannot safely read contract storage directly."* A real, documented-in-code landmine. |
| Store `finalized` / `reasoning` / score in one `@allow_storage` dataclass result, exposed via `gl.public.view` | Verdict is publicly readable — satisfies "verifiable" |
| Accept a JSON string arg, `json.loads` inside | Keeps the calldata schema small |
| `if len(parsed) < 2: raise` | Refuse to judge a trivial case |

## 4. Test harness — the highest-leverage thing to copy

This is what separates a serious build from a demo, and it is free.

- `apps/genlayer/gltest.config.yaml`:
  ```yaml
  networks:
    default: localnet
    localnet:
      url: http://127.0.0.1:4001/api
      chain_type: localnet
      leader_only: true
      default_wait_retries: 60
      default_wait_interval: 2
  paths:
    contracts: contracts
  ```
- `pyproject.toml`: Python `>=3.12,<3.13`, deps `genlayer-test[sim]==0.28.0`, `genvm-linter==0.10.0`,
  `eth-account==0.13.3`, `eth-utils==5.0.0`, `requests==2.31.0`, `python-dotenv==1.0.1`
- Commands: `uv run pytest tests/direct/ -v`, `uv run gltest tests/integration/ -v -s`,
  `pnpm test:genlayer-local`, `pnpm test:genlayer-orchestration`
- Integration tests use `from gltest import get_contract_factory`, then
  `factory.deploy(args=[...])`, `judge.get_result(args=[]).call()`, and the assertions
  `from gltest.assertions import tx_execution_succeeded, tx_execution_failed`
- `conftest.py` **starts its own GLSim instance** — tests are hermetic
- They ship a `sitecustomize.py` containing a workaround for a `glsim` storage-allocation bug
  (`class is not marked for usage within storage, please annotate it with @allow_storage`)

**Implication: we can run the entire M0 consensus gate locally against GLSim, with no network
dependency, before touching studio-dev.** That removes the biggest schedule risk in the plan.

## 5. Frontend stack (they got 2000 with this)

`apps/genlayer/CLAUDE.md`: **Next.js 15, React 19, TypeScript, Tailwind, TanStack Query,
Wagmi/Viem, MetaMask.** They set `NEXT_PUBLIC_CONTRACT_ADDRESS` in `frontend/.env` and deploy via
`npm run deploy` after `genlayer network`. No framework change is needed for us — and note
`NEXT_PUBLIC_*` matches the naming already in this project's `.env`.

## 6. What they store back after finality

> "the deployed contract address; transaction hashes for deploy / submit / finalize; final reasoning
> from GenLayer; the transparent score breakdown used to select finalists; peer review count and
> aggregate peer feedback summary; runtime check summary and evidence references; the winning team ID"

Every intermediate artifact is retained and linkable. **Do the same:** persist our evidence bundle
(URL, screenshot-equivalent, console errors, the exact tx hashes) and link it from the UI. The
30%-for-runtime-evidence line `[B2]` is a hint that this is literally graded.

## 7. The prompt-injection posture, in their code

`gemini_score` is labelled *"advisory pre-score from another AI (0-100), **you may disagree**"*, and
the prompt says *"GenLayer should be prompted to treat the weighted score as important evidence, not
as an automatic result."* That is the right defence for R4: **downstream LLM input is data, never
authority.** Adopt the same phrasing in our judge prompt.

## 8. Honest limits of this teardown

- **No license file** in the repo. Treat as **reference-only, do not copy code**. Re-implement the
  patterns; do not vendor `hackathon_judge.py`. Check licensing before any reuse.
- 1 star, 1 fork — popularity is *not* evidence of quality here; the award is.
- I did **not** run their code, install their deps, or exercise the live platform.
- Their business model (paid challenges, agents compete) is not our model; only the *engineering
  shape* transfers.

## 9. Changes this forces on the original plan

| Original plan | Change | Why |
|---|---|---|
| M0 = "fetch live data inside the contract, 3/3 finalization" | Keep, but run it **against local GLSim via `gltest`** first, then studio-dev | Hermetic, no network flakiness, and they prove this works `[B7]` |
| Consensus on the hot path of every submission | **Restructure to two-stage**: deterministic evidence collection off-chain → consensus only for the final verdict | Their explicit architecture choice `[B7]`; drastically lowers R2 |
| Compare reasoning across models | **Never.** Compare only a discrete `verdict` enum (Partial Field Matching) | Their code comment + GenLayer "Pattern 1" `[B7]` |
| (not previously planned) | Add a `gltest` test suite + `genvm-linter` to the definition of done | Graded on completeness; also our own regression safety |
| (not previously planned) | Emit and display runtime evidence (HTTP status, console errors, screenshots) for our own frontend | ~30% of their finalist score was runtime evidence `[B7]` |
| (not previously planned) | Store + surface all tx hashes (deploy / submit / finalize) in the UI | "verifiable on-chain by anyone" was the award language `[B2]` |
| Deploy target | **studio-dev** (user decision, 2026-10-01) — chain 61997 | `SOURCES.md` [A14]; user's instruction |
