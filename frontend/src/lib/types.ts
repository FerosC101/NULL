export type Assessment = "SUPPORTED" | "CONTRADICTED" | "PARTIALLY IDENTIFIED" | "UNDERDETERMINED" | "UNVERIFIED";

export interface Me {
  user: { id: string; email: string; name: string; title: string; role: string; permissions: string[] };
  workspace: { id: string; name: string; is_demo: boolean; active_dataset: string };
  ai: AiStatus;
}

export interface AiStatus {
  provider: string;
  base_url: string;
  key_configured: boolean;
  model_id: string;
  reasoning_mode: string;
  reasoning_effort: string;
  active: "meta" | "deterministic";
  blocker: string | null;
}

export interface InvestigationSummary {
  id: string;
  ref: string;
  name: string;
  claim: string;
  status: string;
  assessment: Assessment;
  dataset: string;
  dataset_label: string;
  source_keys: string[];
  assignee: string;
  created_at: string;
  updated_at: string;
  conclusion?: string;
}

export interface TimelineItem {
  stage: string;
  label: string;
  status: string;
  detail: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface PredictionResult {
  observable: string;
  label: string;
  expects: "zero" | "positive" | "any";
  hard: boolean;
  p_positive: number;
  reason: string;
  outcome: "matched" | "violated" | "inconclusive" | "untested" | "indifferent";
}

export interface RealityView {
  label: string;
  title: string;
  statement: string;
  claim_true: boolean;
  origin: string;
  assumptions: string[];
  compatibility: string;
  supporting: string[];
  contradicting: string[];
  challenge: string;
  predictions: PredictionResult[];
}

export interface EvidenceView {
  ref: string;
  source_key: string;
  observable: string;
  observable_label: string;
  observation: string;
  observed_at: string;
  reliability: string;
  reliability_basis: string;
  relevance: string;
  primary: boolean;
  state: string | null;
  value: number | null;
  provenance: {
    tool: string;
    execution_id: string;
    method: string;
    sources: string[];
    dataset: string;
    record_ids: number[];
    sha256: string;
  };
}

export interface CheckView {
  id: string;
  tool: string;
  title: string;
  procedure: string;
  rationale: string;
  distinguishes: string[];
  information_gain_bits: number;
  permissions: string[];
  operational_impact: string;
  requires_sources: string[];
  status: string;
  error: string;
  decided_by: string | null;
  decided_at: string | null;
}

export interface FindingView {
  id: string;
  key: string;
  kind: string;
  title: string;
  body: string;
  severity: string;
  evidence_refs: string[];
}

export interface VerificationRunView {
  id: string;
  passed: boolean;
  recurrence: boolean;
  summary: string;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface RemediationView {
  id: string;
  ref: string;
  key: string;
  investigation_id: string;
  investigation_ref?: string;
  finding: string;
  root_cause: string;
  action: string;
  priority: string;
  risk_addressed: string;
  owner: { id: string; name: string };
  approval_status: string;
  execution_status: string;
  verification_status: string;
  verification_criteria: string;
  verification_procedure: string;
  attempts: number;
  decision_note: string;
  can_simulate_recurrence: boolean;
  runs: VerificationRunView[];
}

export interface ToolExecutionView {
  id: string;
  tool: string;
  role: string;
  status: string;
  records_read: number;
  error: string;
  started_at: string;
  finished_at: string | null;
}

export interface InvestigationDetail extends InvestigationSummary {
  objective: string;
  scope: { window_start: string; window_end: string; window_label: string; assets_label: string };
  compiled_claim: { kind: string; interpretation: string; compiler: string; notes: string[] };
  assessment_rationale: string;
  limitations: string[];
  ledger: { observed?: string[]; inferred?: string[]; assumed?: string[]; unknown?: string[]; would_change?: string[] };
  explorer_notes: { text: string; evidence_refs: string[] }[];
  reasoning_mode: string;
  reasoning_note: string;
  error: string;
  timeline: TimelineItem[];
  realities: RealityView[];
  evidence: EvidenceView[];
  assumptions: { key: string; text: string; status: string; basis: string }[];
  findings: FindingView[];
  checks: CheckView[];
  tool_executions: ToolExecutionView[];
  remediations: RemediationView[];
}

export interface CoverageSummary {
  hosts: number;
  reporting: number;
  never_enrolled: string[];
  stale: string[];
  by_class: { asset_class: string; hosts: number; reporting: number; uncovered: string[] }[];
}

export interface OverviewData {
  metrics: Record<string, number>;
  assurance: {
    dataset: string;
    coverage: CoverageSummary | null;
    collection_weaknesses: { subnet: string; missing_hours: number; first: string }[];
    disconnected_sources: { key: string; name: string }[];
    status_counts: Record<string, number>;
    remediation: { pending: number; approved: number; executed: number; verified: number; total: number };
  };
  recent: InvestigationSummary[];
  attention: { kind: string; severity: string; title: string; detail: string; href: string }[];
}

export interface AssuranceData {
  preventive: {
    dataset: string;
    coverage: CoverageSummary | null;
    disconnected_sources: { key: string; name: string }[];
    collection_weaknesses: { subnet: string; missing_hours: number; first: string }[];
    emerging_risks: { title: string; body: string; severity: string }[];
    unavailable: { key: string; reason: string }[];
    unverified_assumptions: {
      text: string;
      status: string;
      basis: string;
      investigation_id: string;
      investigation_ref: string;
    }[];
  };
  remediations: RemediationView[];
}

export interface SourceView {
  key: string;
  name: string;
  description: string;
  mode: string;
  status: string;
  restricted: boolean;
  permissions: string[];
  last_sync_at: string | null;
  records: number;
  earliest: string | null;
  latest: string | null;
  coverage: string | null;
}

export interface InvestigationOptions {
  datasets: { key: string; label: string }[];
  windows: { hours: number; label: string }[];
  asset_classes: { key: string; label: string }[];
  sources: { key: string; name: string; status: string; mode: string; restricted: boolean }[];
}

export interface GraphNodeView {
  id: string;
  kind: string;
  label: string;
  investigation_id: string | null;
  data: Record<string, string | undefined>;
}

export interface GraphEdgeView {
  id: string;
  source: string;
  target: string;
  relation: string;
  explanation: string;
  investigation_id: string;
}

export interface ReportSummary {
  id: string;
  ref: string;
  investigation_id: string;
  name: string;
  investigation_ref: string;
  assessment: Assessment;
  provisional: boolean;
  sha256: string;
  created_at: string;
}
