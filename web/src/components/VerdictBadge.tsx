import type { Verdict } from "@/lib/types";

const STYLE: Record<string, { bg: string; fg: string; hint: string }> = {
  CONFIRMED_EXPLOIT: {
    bg: "#3a1418",
    fg: "#ff6b6b",
    hint: "Consensus froze the target with a mandatory auto-expiry.",
  },
  FALSE_REPORT: {
    bg: "#12291d",
    fg: "#4ade80",
    hint: "Nothing was frozen. The evidence contradicted the claim.",
  },
  INSUFFICIENT_EVIDENCE: {
    bg: "#2c2617",
    fg: "#ffc857",
    hint: "No action taken. The evidence was missing or ambiguous.",
  },
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  const s = STYLE[verdict] ?? {
    bg: "#1b2231",
    fg: "#8b98ab",
    hint: "Unrecognised verdict.",
  };
  return (
    <span
      className="pill"
      style={{ background: s.bg, color: s.fg }}
      title={s.hint}
    >
      {verdict}
    </span>
  );
}
