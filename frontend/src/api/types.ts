export type ApplicationStatus =
  | "saved"
  | "applied"
  | "screening"
  | "interviewing"
  | "offer"
  | "accepted"
  | "rejected"
  | "withdrawn";

export type RemoteType = "onsite" | "hybrid" | "remote" | "unknown";

export type DocumentKind =
  | "resume"
  | "cover_letter"
  | "portfolio"
  | "offer_letter"
  | "other";

export type EventKind =
  | "status_change"
  | "note"
  | "interview"
  | "outreach"
  | "followup";

export type AssistantRunKind = "match_analysis" | "cover_letter" | "interview_prep";

export const APPLICATION_STATUSES: ApplicationStatus[] = [
  "saved",
  "applied",
  "screening",
  "interviewing",
  "offer",
  "accepted",
  "rejected",
  "withdrawn",
];

/** Statuses that are still in play, in pipeline order. */
export const ACTIVE_STATUSES = [
  "saved",
  "applied",
  "screening",
  "interviewing",
  "offer",
] as const satisfies readonly ApplicationStatus[];

export type ActiveStatus = (typeof ACTIVE_STATUSES)[number];

export interface Company {
  id: string;
  name: string;
  website: string | null;
  industry: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobPosting {
  id: string;
  company_id: string | null;
  company: Company | null;
  title: string;
  location: string | null;
  remote_type: RemoteType;
  employment_type: string | null;
  seniority: string | null;
  salary_min: string | number | null;
  salary_max: string | number | null;
  salary_currency: string | null;
  source_url: string | null;
  raw_text: string | null;
  extracted: ExtractedPosting | null;
  created_at: string;
  updated_at: string;
}

export interface ExtractedPosting {
  responsibilities?: string[];
  requirements?: string[];
  nice_to_have?: string[];
  tech_stack?: string[];
  benefits?: string[];
  [key: string]: unknown;
}

export interface ApplicationEvent {
  id: string;
  application_id: string;
  kind: EventKind;
  occurred_at: string;
  summary: string;
  detail: string | null;
}

export interface StoredDocument {
  id: string;
  application_id: string | null;
  kind: DocumentKind;
  filename: string;
  content_type: string;
  size_bytes: number;
  storage_key: string;
  created_at: string;
}

export interface Application {
  id: string;
  posting_id: string;
  posting: JobPosting | null;
  status: ApplicationStatus;
  applied_on: string | null;
  next_action: string | null;
  next_action_on: string | null;
  excitement: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApplicationDetail extends Application {
  events: ApplicationEvent[];
  documents: StoredDocument[];
}

export interface PipelineSummary {
  by_status: Partial<Record<ApplicationStatus, number>>;
  total: number;
  needs_action: number;
}

export interface MatchGap {
  requirement: string;
  evidence: string | null;
  severity: string;
}

export interface MatchAnalysis {
  overall_fit: number;
  summary: string;
  strengths: string[];
  gaps: MatchGap[];
  resume_suggestions: string[];
  talking_points: string[];
}

export interface AssistantRun {
  id: string;
  application_id: string | null;
  kind: AssistantRunKind;
  model: string;
  output_text: string | null;
  output_json: MatchAnalysis | null;
  input_tokens: number | null;
  output_tokens: number | null;
  created_at: string;
}

export interface AssistantStatus {
  enabled: boolean;
  model: string;
}
