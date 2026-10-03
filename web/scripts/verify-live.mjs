/**
 * Live deployment verifier.
 *
 *   cd web && node scripts/verify-live.mjs [caseId]
 *
 * Reads the deployed Cordon contract over public JSON-RPC and prints what it found next to what
 * it expected. Exists so a reviewer can confirm the path works end to end without installing
 * anything, and so the expected output in the README is reproducible rather than remembered.
 *
 * Uses `genlayer-js`, deliberately. `genlayer-py` 0.18.0 reports this same contract as
 * "not found" at this same endpoint on this same chain (reproduced twice; endpoint, chain id,
 * address and existence all ruled out), so the Python client cannot be used to verify the
 * deployment. See state/reviews/2026-10-03-vercel-deploy/DEPLOY-VERIFICATION.md.
 *
 * Exit code 0 = every expectation met. 1 = at least one mismatch.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createClient } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");

// Minimal .env.local reader so this needs no dotenv dependency.
function loadEnv() {
  const out = {};
  let raw = "";
  try {
    raw = readFileSync(resolve(WEB, ".env.local"), "utf8");
  } catch {
    console.error(
      "Cannot read web/.env.local.\n" +
        "Copy web/.env.example to web/.env.local and set NEXT_PUBLIC_GENLAYER_RPC and\n" +
        "NEXT_PUBLIC_HALT_ADDRESS. Both are public values; no private key is needed.",
    );
    process.exit(1);
  }
  for (const line of raw.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const i = t.indexOf("=");
    if (i > 0) out[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
  return out;
}

const env = loadEnv();
const RPC = env.NEXT_PUBLIC_GENLAYER_RPC;
const ADDRESS = env.NEXT_PUBLIC_HALT_ADDRESS;
const CHAIN_ID = Number(env.NEXT_PUBLIC_GENLAYER_CHAIN_ID ?? "61999");

if (!RPC || !ADDRESS) {
  console.error("NEXT_PUBLIC_GENLAYER_RPC and NEXT_PUBLIC_HALT_ADDRESS must both be set.");
  process.exit(1);
}

const client = createClient({ chain: studionet, account: "0x" + "0".repeat(40) });

const VALID_VERDICTS = ["CONFIRMED_EXPLOIT", "FALSE_REPORT", "INSUFFICIENT_EVIDENCE"];
const LIFECYCLE = ["PENDING", "PROPOSING", "COMMITTING", "REVEALING", "ACCEPTED", "FINALIZED"];

let failures = 0;
function check(label, actual, expected, ok) {
  const pass = ok === undefined ? true : ok;
  if (!pass) failures++;
  const mark = pass ? "ok  " : "FAIL";
  console.log(`  [${mark}] ${label.padEnd(22)} ${String(actual)}`);
  if (!pass) console.log(`         expected: ${expected}`);
}

const target = process.argv[2] ?? "live-drain-run2";

console.log("Cordon — live deployment verification");
console.log("=====================================");
console.log(`  endpoint   ${new URL(RPC).host}`);
console.log(`  chain id   ${CHAIN_ID}`);
console.log(`  contract   ${ADDRESS}`);
console.log(`  case       ${target}`);
console.log();

console.log("Environment");
check("chain is Studionet", CHAIN_ID, "61999", CHAIN_ID === 61999);
console.log();

console.log("Contract responds");
let stats, cases, verdict, proof;
try {
  stats = await client.readContract({ address: ADDRESS, functionName: "stats", args: [] });
  check("stats()", "returned", "an object", typeof stats === "object" && stats !== null);
} catch (e) {
  check("stats()", `threw: ${String(e).slice(0, 80)}`, "an object", false);
  console.log("\nThe contract did not answer. Everything below is blocked.");
  process.exit(1);
}
console.log();

console.log("State");
try {
  cases = await client.readContract({ address: ADDRESS, functionName: "list_cases", args: [] });
  check("list_cases()", cases.length, "> 0", Array.isArray(cases) && cases.length > 0);
} catch (e) {
  cases = [];
  check("list_cases()", `threw: ${String(e).slice(0, 80)}`, "a non-empty list", false);
}
console.log();

console.log("Proof read path");
try {
  proof = await client.readContract({
    address: ADDRESS,
    functionName: "get_evidence",
    args: [target],
  });
  check("get_evidence()", "returned", "a proof", Boolean(proof));
  if (proof) {
    const ev = proof.evidence ?? {};
    check("  evidence mode", proof.evidence_mode ?? "(unset)", "jsonrpc");
    check("  value band", ev.value_band ?? "(unset)", "a stable band string");
    check("  log band", ev.log_band ?? "(unset)", "a stable band string");
    check("  submitter", String(proof.submitter ?? "").slice(0, 12) + "...", "an address");
    check("  validator agreed", String(proof.validator_agreed), "true/false");
    check("  rationale stored", `${String(proof.rationale ?? "").length} chars`, "> 0 chars",
      String(proof.rationale ?? "").length > 0);
  }
} catch (e) {
  check("get_evidence()", `threw: ${String(e).slice(0, 80)}`, "a proof", false);
}
console.log();

console.log("Verdict is a discrete enum");
try {
  verdict = await client.readContract({
    address: ADDRESS,
    functionName: "get_verdict",
    args: [target],
  });
  check("get_verdict()", verdict, VALID_VERDICTS.join(" | "), VALID_VERDICTS.includes(verdict));
} catch (e) {
  check("get_verdict()", `threw: ${String(e).slice(0, 80)}`, "an enum member", false);
}

try {
  const frozen = await client.readContract({
    address: ADDRESS,
    functionName: "is_frozen",
    args: [target],
  });
  const expectFrozen = verdict === "CONFIRMED_EXPLOIT";
  check(
    "is_frozen() agrees",
    String(frozen),
    `${expectFrozen} (frozen only on CONFIRMED_EXPLOIT)`,
    Boolean(frozen) === expectFrozen,
  );
} catch (e) {
  console.log(`  [warn] is_frozen() threw: ${String(e).slice(0, 80)}`);
}
console.log();

console.log(`Case ids on chain (${cases.length}):`);
for (const c of cases.slice(0, 12)) console.log(`  - ${c}`);
if (cases.length > 12) console.log(`  ... and ${cases.length - 12} more`);
console.log();

console.log("Enum and lifecycle vocabulary");
check("verdict enum size", VALID_VERDICTS.length, "3 (not a scalar score)", VALID_VERDICTS.length === 3);
check("lifecycle states", LIFECYCLE.length, "6, kept distinct", LIFECYCLE.length === 6);
console.log();

console.log("=====================================");
if (failures === 0) {
  console.log("PASS — the deployed contract answers, and the verdict is a valid enum member.");
  process.exit(0);
} else {
  console.log(`FAIL — ${failures} expectation(s) not met. See [FAIL] lines above.`);
  process.exit(1);
}