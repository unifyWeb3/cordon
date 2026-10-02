export type Verdict =
  | "CONFIRMED_EXPLOIT"
  | "FALSE_REPORT"
  | "INSUFFICIENT_EVIDENCE";

export const VERDICTS: Verdict[] = [
  "CONFIRMED_EXPLOIT",
  "FALSE_REPORT",
  "INSUFFICIENT_EVIDENCE",
];

/** The on-chain evidence record. Mirrors the @allow_storage dataclass in the contract. */
export type Evidence = {
  source_url: string;
  tx_found: boolean;
  receipt_ok: boolean;
  success: boolean;
  receipt_status: string;
  input_selector: string;
  selectors: string;
  repeated_selectors: string;
  value_band: string;
  log_band: string;
  signature: string;
};

/** The on-chain proof record. Mirrors the @allow_storage dataclass in the contract. */
export type Proof = {
  case_id: string;
  submitter: string;
  target: string;
  tx_hash: string;
  claim: string;
  evidence_url: string;
  evidence_mode: string;
  submitted_at: string;
  finalized: boolean;
  verdict: Verdict | string;
  rationale: string;
  evidence: Evidence;
  evidence_signature: string;
  leader_verdict: string;
  validator_agreed: boolean;
  frozen: boolean;
  expires_at: string;
  unfrozen_at: string;
};

export type ContractStats = {
  submits: number;
  freezes: number;
  cases: number;
  owner: string;
  evidence_url_template: string;
  default_freeze_seconds: number;
};
