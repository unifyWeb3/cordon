# UI teardown — why ours does not sell, and what the ecosystem does instead

Date: 2026-10-02. Reviewer: discovery session.
Trigger: "the UI is quite not selling the product as it seems to do so, not even relatable."

**Verdict: your instinct is right, and the cause is structural rather than cosmetic.** Our page is a
*working console*. Every one of the three builders I inspected ships a *landing page that explains the
product before showing the console*. We skipped the first half entirely — and the rubric line we
need most is the one that half serves.

Inspected: `enoch208/Dirac`, `mrnetwork0001/Inktoll`, `mystiquemide/triage` (source read, not
screenshots), against our `web/`.

---

## 1. The comparison

| | **Ours** | **Dirac** (enoch208) | **Inktoll** (mrnetwork0001) | **triage** (mystiquemide) |
|---|---|---|---|---|
| Stars | — | 1 | **60** | 1 |
| Stack | Next 15, raw inline styles | Next, Tailwind design system | Next, Framer Motion, glassmorphism | Vue 3, Tailwind, 29 KB `style.css` |
| Structure | **1 page** | Nav → Hero → HowItWorks → **DemoDuel** → FeatureBento → PotBanner → Footer | Onboarding tour, personas, leaderboards | Hero shot, feature list, 2 screenshots |
| Files | `page.tsx` 379 L + 4 components | **18 components** | full dashboard | `App.vue` 875 B + components |
| Does it explain the problem? | **No** | Yes — `hero` + `how-it-works` | Yes — vision first, then features | Yes — "Why This Exists" |
| Is there something to *touch*? | **No** | **Yes — `demo-duel.tsx`, playable rock-paper-scissors** | Yes — Joyride tour | No |
| Mobile considered | No | `sm:`/`lg:` throughout | Screenshots both widths | Screenshot at 260 px |

Star counts are *not* evidence of quality here — enoch208 and mystiquemide both have 1-star repos and
Dirac won nothing I can verify. I read the source because the *structure* is the transferable part,
not the polish.

## 2. What Dirac does that we don't — the single most important finding

`enoch208/Dirac/frontend/components/demo-duel.tsx` is an **interactive rock-paper-scissors game
embedded in the landing page.** No wallet, no contract, no signature. Click, the state changes, you
understand the product in fifteen seconds.

And the design is deliberate, not accidental — `demo-duel.tsx:9` loads a local engine:

```ts
import { createDuel, playRound, type DuelResult, type DuelState, type Move } from "@/lib/demo-engine";
```

A pure client-side simulation that teaches the core idea before asking for anything. Their
`how-it-works.tsx` then narrates it in four steps (`STEPS` from `lib/content`).

**This is exactly what our product is missing, and it maps one-to-one onto our actual live data.** We
already have three adjudicated cases on-chain. They are a ready-made demo:

| Case | Input | Verdict | Why it's a great demo beat |
|---|---|---|---|
| `live-missing` | a hash not on chain | `INSUFFICIENT_EVIDENCE` | "No evidence → no freeze" — the safe default |
| `live-real-tx` | real tx + *fabricated* claim | `FALSE_REPORT` | It caught a lie |
| `live-drain` | 14 repeated `Transfer`s + drain claim | `FALSE_REPORT` | **It refused the scary-looking one** |

`live-drain` is the story. A transaction that *looks* like a drain — 14 repeated transfer events,
`logs=MANY`, the exact signature — and the committee says no, because `value=ZERO` and a
non-transfer selector contradict the claim. **That single case is the product's entire argument, and
right now a grader has to read a README table to find it.**

The build session already wrote it up honestly in the README. The problem is the *page* buries it
under a form and a chain ID.

## 3. Four concrete gaps

**G1 — No problem statement.** Our page opens straight into `<h1>Anyone can propose a freeze.</h1>`
then immediately a "GenLayer network / chain 61999 / Contract 0x37E08…" card. A visitor's first
frame is a chain ID. `dirac` leads with the *problem*, `inktoll` with "The Vision & Problem", `triage`
with "Why This Exists". Ours has the best problem of the three — a 46-minute response time to a
$292M drain, and a protocol currently in court over a freeze `[D1][D5]` — and states none of it.

**G2 — The headline case is invisible.** All three verdicts sit behind a case-chip selector
(`{selected}`). Nothing surfaces automatically. A grader who doesn't click sees an empty selector.

**G3 — No touchable anything.** Dirac has a playable demo; Inktoll has a Joyride tour. We have a
wallet prompt and a form. First-time visitor friction: connect wallet → type a 42-char address →
paste a 66-char hash → write a claim. **We gate the explanation behind four steps of setup.**

**G4 — Raw inline styles.** `page.tsx` uses `style={{ fontSize: 16, margin: "0 0 12px" }}` throughout.
`styles.card`, `.btn`, `.sub` are few shared classes. Dirac has `gradient-border`, `glow-accent`,
`btn-glass`, `text-gradient-accent`, staggered `Reveal` animations, `font-display`. Ours looks like
a debug view because it *is* styled like one — and "state-of-the-art UX" is a phrase Inktoll's README
uses to describe exactly this gap.

## 4. What is actually working — do not throw it

Being fair to the build session, three things are right and should survive the redesign:

- **The lifecycle component is genuinely good.** `Stages` renders PENDING → PROPOSING → COMMITTING →
  ACCEPTED → FINALIZED as *distinct* states, with `txExecutionResult` checked separately from status
  and an explicit message when consensus finalizes a failed call `[A18]`. That is the rubric line
  *"handles the full transaction lifecycle"* `[A2]`, and Dirac's marketing page has nothing like it.
- **The honest-claim text is already written.** The 46-minute admission, "the claim is treated as
  data, never as instructions", the injection posture. Just needs to move from a form footnote to the
  page body.
- **The data is real and already on-chain.** Three verdicts, real digests, explorer links.

The fix is **additive**: put a landing narrative in front of the existing console. Not a rewrite.

## 5. What I checked and could not check

- I read source, not rendered pages. Dirac's *visual* quality is inferred from class names
  (`glass-panel`, `nebula-background`, `progressive-blur`) — I have **not** seen it render, and I
  cannot judge whether it looks better than ours, only that it is structured to.
- No browser in this environment, so I have never seen our page either.
- Star counts and README adjectives are self-reported. Inktoll's "state-of-the-art glassmorphism"
  is marketing copy; I'm citing it as *evidence of intent*, not quality.
- I did not run any of their code or install their deps.

## 6. Recommendation

Do not let this compete with Phase 1. **Phase 1 (the EVM emit) is the only remaining gap on the
headline claim, and the rubric is strict — "most submissions are rejected" `[A2]`.** But this UI work
is cheap, high-leverage, and gates the demo video, so it belongs immediately after.

The specific move, in priority order:

1. **Auto-surface `live-drain` on load.** One card above the fold, verdict badge, evidence digest,
   and one line: *"14 repeated transfer events, and the committee still said no."* Highest
   value-per-minute change available.
2. **Add a problem section above the console.** Three sentences: 46 minutes, $292M, and the freeze
   currently in court. With a link to the evidence.
3. **Add a no-wallet demo path.** Not rock-paper-scissors — walk the three real cases as a guided
   sequence. Same move as Dirac's `demo-duel`, using our actual on-chain verdicts instead of a toy.
4. **Then** the token/spacing pass: a real type scale, a verdict-colour system
   (`CONFIRMED_EXPLOIT` / `FALSE_REPORT` / `INSUFFICIENT_EVIDENCE` as three visually distinct states),
   and `Stages` promoted from a widget to the centrepiece it already is.

Skip the nebula backgrounds and glassmorphism. The thing that makes those projects legible is the
*narrative structure*, not the effects — and a demo video records at 30fps, where subtle animation
invisible anyway.