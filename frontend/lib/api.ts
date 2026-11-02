/**
 * Thin typed adapter over the unchanged FastAPI v1 contract.
 * Types mirror backend Pydantic models / response dicts (see docs/03-api-contract-inventory.md).
 * No metric is recalculated here; the backend is the single source of numeric truth.
 */

export type Platform = "Facebook" | "Instagram" | "Google" | "TikTok" | "YouTube";
export const PLATFORMS: Platform[] = ["Facebook", "Instagram", "Google", "TikTok", "YouTube"];

export type Capability = { id: string; phase: number; available: boolean; reason: string };

export type Manifest = {
  id: string;
  workspace_id: "local";
  name: string;
  source: "synthetic_generator" | "advertiser_csv" | "synthetic_csv";
  is_synthetic: boolean;
  original_filename: string | null;
  import_profile: string | null;
  imported_at: string;
  currency: "PKR";
  original_currency: string;
  exchange_rate: number;
  date_granularity: "daily" | "weekly";
  date_start: string;
  date_end: string;
  rows: number;
  conversion_definition: string;
  attribution_window: string;
  revenue_source: "synthetic" | "ad_platform_reported";
  coverage: Record<string, number>;
  warnings: string[];
  data_ready_for_revenue: boolean;
  options: Record<string, string[]>;
  seed: number | null;
  parent_dataset_id?: string | null;
  reporting_evidence?: Record<string, string>;
  provenance_flags?: Record<string, boolean>;
  import_mapping?: Record<string, unknown>;
};

export type WorkspaceState = {
  api_version: "v1";
  phase: number;
  mode: "local_single_user";
  workspace_id: string;
  currency: "PKR";
  dataset_count: number;
  selected_dataset_id: string | null;
  selected_dataset: Manifest | null;
  datasets: Manifest[];
  revenue_source: string | null;
  model_status: "not_trained" | "trained" | "validated";
  hosting_notice: string | null;
  connected_providers: string[];
  capabilities: Capability[];
};

export type Cell = string | number | boolean | null;
export type Row = Record<string, Cell>;

export type Totals = {
  rows: number;
  impressions: number | null;
  clicks: number | null;
  spend: number | null;
  conversions: number | null;
  revenue: number | null;
  ctr: number | null;
  cpc: number | null;
  cpa: number | null;
  cvr: number | null;
  roas: number | null;
  coverage: Record<string, number>;
};
export type Aggregate = Totals & { name: string };
export type Analytics = {
  dataset: Manifest;
  totals: Totals;
  platforms: Aggregate[];
  trend: Aggregate[];
  trend_grain: string;
  group_by: string;
  table: Aggregate[];
  table_total: number;
  page: number;
  page_size: number;
  sort: string;
  direction: string;
  filters: Record<string, string>;
};

export type ReportingHint = {
  value: string | null;
  status: "detected" | "partial" | "missing" | "mixed";
  evidence: string;
};
export type ReportingHints = Record<"conversion_definition" | "attribution_window", ReportingHint>;

export type Stage = {
  token: string;
  filename: string;
  profile: string;
  columns: string[];
  row_count: number;
  preview: Row[];
  suggested_mapping: Record<string, string>;
  mapping_details: Record<
    string,
    { status: string; reason: string; candidates: { column: string; confidence: number; reason: string }[] }
  >;
  reporting_hints?: ReportingHints;
  detected_currencies: string[];
  warnings: string[];
};
export type ImportOptions = {
  name: string;
  mapping: Record<string, string>;
  default_platform: Platform | null;
  original_currency: string;
  exchange_rate: number | null;
  date_format: "auto" | "%Y-%m-%d" | "%d/%m/%Y" | "%m/%d/%Y" | "%G-W%V";
  date_granularity: "auto" | "daily" | "weekly";
  conversion_definition: string;
  attribution_window: string;
  is_synthetic: boolean;
  exclude_invalid: boolean;
  drop_duplicates: boolean;
  confirmed: boolean;
};
export type ValidationReport = {
  date_granularity: "daily" | "weekly";
  input_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  excluded_rows: number;
  can_import: boolean;
  is_synthetic: boolean;
  coverage: Record<string, number>;
  warnings: string[];
  errors: { field: string; message: string; count: number; rows: number[] }[];
  preview: Row[];
  data_ready_for_revenue: boolean;
  reporting_hints?: ReportingHints;
};

// ---- ML -------------------------------------------------------------------
export type Score = { rows: number; mae: number; rmse: number; r2?: number | null; wape: number | null };
export type Evaluation = {
  model: Score;
  baseline: Score;
  platforms: { platform: string; model: Score; baseline: Score }[];
};
export type ModelResult = {
  algorithm: string;
  fallback_reason: string | null;
  elapsed_seconds: number;
  target: string;
  grain: string;
  date_granularity?: string;
  features: string[];
  splits: Record<string, { rows: number; start: string; end: string }>;
  coverage: {
    input_rows: number;
    eligible_rows: number;
    excluded_rows: number;
    maturity_cutoff: string;
    label_lag_days: number;
  };
  test: Evaluation;
  validation: Evaluation;
  acceptance: { eligible: boolean; reasons: string[]; policy: string };
  spend_ranges: Record<string, { min: number; max: number }>;
  feature_importance: { feature: string; importance: number }[];
  versions: Record<string, string>;
  limitations: string[];
  recommendations_enabled: boolean;
  recommendations_reason: string;
  uncertainty: string;
};
export type ModelJob = {
  id: string;
  status: string;
  stage: string;
  message: string;
  created_at: string;
  completed_at: string | null;
  config: { dataset_id: string; seed: number; as_of_date: string; label_lag_days: number };
  dataset: Manifest;
  result: ModelResult | null;
  cancel_requested: boolean;
  input_sha256: string;
};
export type MLState = { jobs: ModelJob[]; active_job: ModelJob | null; versions: Record<string, string | null> };
export type ReportingSetup = {
  fields: ReportingHints;
  needs_answers: boolean;
  mixed: boolean;
  financial_complete: boolean;
};
export type Readiness = {
  ready: boolean;
  reasons: string[];
  coverage?: ModelResult["coverage"];
  splits?: ModelResult["splits"];
  reporting_setup?: ReportingSetup | null;
};
export const modelFinished = (s: string) => ["succeeded", "failed", "cancelled", "interrupted"].includes(s);

// ---- Optimizer --------------------------------------------------------------
export type PlatformLimit = {
  platform: Platform;
  min_percent: number;
  max_percent: number;
  min_amount?: number;
  max_amount?: number | null;
};
export type PlanMethod = "auto" | "model" | "baseline" | "historical" | "evidence";
export type PlanConfig = {
  dataset_id: string;
  method: PlanMethod;
  model_id: string | null;
  budget: number;
  step: number | null;
  start_date: string;
  horizon_days: number;
  as_of_date: string;
  label_lag_days: number;
  platforms: PlatformLimit[];
};
export type Allocation = {
  platform: string;
  budget: number;
  share_percent: number;
  estimated_revenue: number | null;
  raw_estimated_revenue: number | null;
  next_step_revenue: number | null;
  effective_min: number;
  effective_max: number;
  requested_min_percent: number;
  requested_max_percent: number;
  reason: string;
};
export type PlanTotals = {
  budget: number;
  estimated_revenue: number | null;
  raw_estimated_revenue: number | null;
  estimated_roas: number | null;
};
export type PlanSummary = {
  id: string;
  created_at: string;
  config: PlanConfig;
  method_label: string;
  totals: PlanTotals;
  is_synthetic: boolean;
};
export type Plan = PlanSummary & {
  forecast_status?: "model" | "baseline" | "historical" | "unavailable";
  forecast_reasons?: string[];
  baseline_assessment?: { eligible: boolean; reasons: string[]; policy: string } | null;
  dataset: Manifest;
  source_sha256: string;
  model_id: string | null;
  objective: string;
  policy: string;
  planning_end: string;
  training_period: { start: string; end: string };
  allocations: Allocation[];
  comparisons: (PlanTotals & { name: string; estimated_difference: number; allocations: Allocation[] })[];
  curves: { platform: string; points: { budget: number; raw_revenue: number; adjusted_revenue: number }[] }[];
  uncertainty: string;
  notice: string;
  limitations: string[];
  prediction_rows: number;
  elapsed_seconds: number;
};
export type OptimizerState = {
  dataset_id: string | null;
  suggested_start: string;
  models: { id: string; algorithm: string; eligible: boolean; reasons: string[]; as_of_date: string; test_end: string }[];
  plans: PlanSummary[];
};

// ---- Big Data Lab ------------------------------------------------------------
export type Engine = "pandas" | "mapreduce" | "spark";
export type ExperimentConfig = {
  kind: "generate" | "benchmark";
  rows: 10000 | 100000 | 1000000 | 10000000;
  seed: number;
  start_date: string;
  end_date: string;
  platforms: Platform[];
  chunk_rows: 10000 | 50000 | 100000;
  engines: Engine[];
  repeats: number;
  workers: number;
  memory_mib: number;
  dataset_id: string | null;
};
export type PlatformTotal = Omit<Aggregate, "coverage">;
export type LabDataset = {
  id: string;
  created_at: string;
  rows: number;
  bytes: number;
  parts: number;
  sha256: string;
  generator_version: string;
  config: Omit<ExperimentConfig, "kind" | "engines" | "repeats" | "workers" | "memory_mib" | "dataset_id">;
  reference: PlatformTotal[];
};
export type EngineResult = {
  engine: string;
  status: string;
  mode?: string;
  message?: string;
  setup_seconds: number | null;
  peak_tree_rss_bytes: number | null;
  median_seconds: number | null;
  median_rows_per_second: number | null;
  aggregate?: PlatformTotal[];
  runs: { repeat: number; elapsed_seconds: number; rows_per_second: number; correct: boolean }[];
};
export type LabEnvironment = {
  hosted?: boolean;
  os: string;
  architecture: string;
  cpu: string;
  logical_cpus: number | null;
  physical_cpus: number | null;
  ram_total_bytes: number | null;
  ram_available_bytes: number | null;
  disk_free_bytes: number;
  python: string;
  packages: Record<string, string | null>;
  java: { major: number; description: string } | null;
  input_format: string;
  engines: { id: Engine; label: string; available: boolean; reason: string }[];
  limits?: Record<string, number>;
};
export type LabJob = {
  id: string;
  status: string;
  stage: string;
  created_at: string;
  updated_at: string;
  config: ExperimentConfig;
  message: string;
  generated_rows: number;
  generation_seconds?: number | null;
  cancel_requested: boolean;
  dataset: LabDataset | null;
  results: EngineResult[];
  environment: LabEnvironment | null;
  benchmark_version?: string;
};
export type LabState = {
  environment: LabEnvironment;
  methodology: Record<string, string>;
  datasets: LabDataset[];
  jobs: LabJob[];
};
export const labTerminal = (s: string) => ["completed", "failed", "cancelled", "interrupted"].includes(s);

// ---- AI (optional NVIDIA) ---------------------------------------------------
export type AIStatus = {
  provider: string;
  model: string;
  configured: boolean;
  key_source: "environment" | "local_file" | "missing";
  verified: boolean;
  checked_at: string | null;
  last_error: string | null;
};
export type ReportKind = "performance" | "model" | "budget";
export type AISummary = {
  dataset_id: string;
  kind: ReportKind;
  summary: Record<string, unknown>;
  local_reference: Record<string, unknown>;
  summary_sha256: string;
  scope: string;
};
export type AIExplanation = {
  text: string;
  provider: string;
  model: string;
  generated_at: string;
  summary_sha256: string;
  dataset_id: string;
  is_synthetic: boolean;
  notice: string;
};

// ---- Commerce pilot ------------------------------------------------------------
export type CommerceMeta = {
  id: string;
  kind: string;
  name: string;
  store_id: string;
  is_synthetic: boolean;
  profile: string;
  created_at: string;
  period_start: string;
  period_end: string;
  timezone: string;
  orders: number;
  line_items: number;
  cost_rows: number;
  order_batch_id?: string;
  ad_dataset_id?: string;
  start_date?: string;
  end_date?: string;
  warnings: string[];
  dependencies?: string[];
  definitions: Record<string, unknown>;
};
export type CommerceState = {
  selected_order_batch_id: string | null;
  orders: CommerceMeta[];
  costs: CommerceMeta[];
  reconciliation: CommerceMeta[];
  profit_plan: CommerceMeta[];
  money_unit: string;
  connected: boolean;
};
export type CommerceAssessment = { eligible: boolean; reasons: string[]; policy: string };
export type CommerceReport = {
  manifest: CommerceMeta;
  orders_manifest: CommerceMeta;
  ad_source: Manifest;
  store: {
    unique_orders: number;
    eligible_orders: number;
    excluded_orders: number;
    net_sales: number | null;
    gross_sales: number | null;
    discounts: number | null;
    merchandise_refunds: number | null;
    net_sales_coverage: number | null;
  };
  advertising: { spend: number | null; platform_reported_revenue: number | null; reported_roas: number | null };
  attribution: {
    matched: number;
    unmatched: number;
    ambiguous: number;
    excluded: number;
    matched_net_sales: number | null;
    order_coverage: number | null;
    unknown_lag_orders: number;
  };
  costs: { coverage: Record<string, number | null>; totals: Record<string, number | null>; total: number | null };
  profit: {
    contribution_after_ads: number | null;
    shipping_income: number | null;
    merchandise_mer: number | null;
    margin: number | null;
    forecast_reasons: string[];
  };
  assessment: CommerceAssessment;
  notice: string;
  reference: {
    provided_net_sales: string | null;
    net_sales_difference: number | null;
    provided_eligible_orders: number | null;
    order_count_difference: number | null;
    origin: string;
  };
  link_total: number;
};
export type ProfitResult = {
  budget: number;
  estimated_contribution_before_ads: number;
  estimated_contribution_profit: number;
  allocations: { platform: string; budget: number; minimum: number; maximum: number }[];
};
export type ProfitPlan = {
  manifest: CommerceMeta;
  result: ProfitResult;
  comparisons: (ProfitResult & { name: string })[];
  assessment: CommerceAssessment;
  notice: string;
};

// ---- Transport ----------------------------------------------------------------
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

/** Calls `/api/v1{path}`. Errors carry the backend's sanitized `detail` text. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...init, cache: "no-store" });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new ApiError(
      "Could not reach the SignalSpend service. Start the local backend (npm run dev) or check the hosted function, then retry.",
      0,
    );
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const text =
      response.status >= 500 && typeof detail !== "string"
        ? "The service could not confirm this action. Refresh before retrying."
        : typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: { msg?: string; loc?: unknown[] }) => d.msg).filter(Boolean).join(" ")
            : "This action could not be completed. Review your inputs and retry.";
    throw new ApiError(text, response.status);
  }
  return body as T;
}

export const post = (body: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong. Please retry.";

export const isAbort = (error: unknown) => error instanceof DOMException && error.name === "AbortError";
