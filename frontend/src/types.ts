export type Project = {
  id: number;
  name: string;
  path: string;
  created_at: string;
  updated_at: string;
};

export type Community = {
  id: number;
  project_id: number;
  code: string;
  name: string;
  region: string;
  households: number;
  average_household_size: number;
  migration_rates: Record<string, number>;
  migration_rate_unit?: "‰";
  age_counts: Record<string, number>;
  population_records?: Array<Record<string, unknown>>;
  population_base_year?: number | null;
  facilities: Record<string, unknown>;
  idle_spaces: Array<Record<string, unknown>>;
  source_file?: string;
  created_at: string;
  updated_at: string;
};

export type CommunityImportIssue = {
  sheet?: string;
  row?: number;
  field: string;
  value?: unknown;
  message: string;
};

export type CommunityImportReport = {
  filename: string;
  total_count: number;
  success_count: number;
  created_count: number;
  updated_count: number;
  failed_count: number;
  issues: CommunityImportIssue[];
  warnings?: string[];
  community?: Community;
};

export type ParameterSet = {
  kind: "population" | "facility";
  data: Record<string, unknown>;
  source_file?: string;
  updated_at: string;
};

export type Dashboard = {
  community_count: number;
  total_households: number;
  total_population: number;
  regions: Record<string, number>;
};

export type PredictionRun = {
  project_name?: string;
  community_names?: string[];
  community_ids?: number[];
  forecast_years?: number[];
  id: number;
  project_id: number;
  kind: "population" | "facility";
  status: "running" | "success" | "failed";
  seed: number;
  output_file?: string;
  error_message?: string;
  started_at: string;
  completed_at?: string;
  report_available?: boolean;
};

export type PredictionResultRow = {
  communityId: number;
  communityCode: string;
  communityName: string;
  year: number;
  data: {
    totalPopulation?: number;
    households?: number;
    ageGroups?: Record<string, number>;
    metrics?: Record<string, number>;
  };
};

export type ModuleEvent = {
  type: string;
  payload?: unknown;
};

export type QualityIssue = { level:"error"|"warning"; code:string; message:string; page:"dashboard"|"population"|"facility"|"communities"; communityId?:number };
export type QualityReport = { kind:"population"|"facility"; ready:boolean; errorCount:number; warningCount:number; checkedCommunities:number; forecastYears:number[]; issues:QualityIssue[] };
