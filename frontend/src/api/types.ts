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

/** An artifact produced for, or attached to, one application. */
export type DocumentKind =
  | "resume"
  | "cover_letter"
  | "interview_prep"
  | "portfolio"
  | "offer_letter"
  | "other";

export const DOCUMENT_KIND_LABELS: Record<DocumentKind, string> = {
  resume: "Resume",
  cover_letter: "Cover letter",
  interview_prep: "Interview prep",
  portfolio: "Portfolio",
  offer_letter: "Offer letter",
  other: "Other",
};

export type ExperienceSource = "imported" | "manual" | "chat";

export interface Highlight {
  id: string;
  text: string;
  sort_order: number;
  source: ExperienceSource;
}

export interface ExperienceRole {
  id: string;
  company: string;
  title: string;
  location: string | null;
  employment_type: string | null;
  start_date: string | null;
  /** Null means current. */
  end_date: string | null;
  summary: string | null;
  sort_order: number;
  source: ExperienceSource;
  highlights: Highlight[];
}

export interface ExperienceStory {
  id: string;
  title: string;
  body: string;
  role_id: string | null;
  skills: string[];
  source: ExperienceSource;
  created_at: string;
}

export interface Education {
  id: string;
  institution: string;
  credential: string | null;
  field: string | null;
  start_date: string | null;
  end_date: string | null;
  notes: string | null;
  sort_order: number;
}

export interface ProfileLink {
  label: string;
  url: string;
}

export interface ExperienceProfile {
  id: string;
  full_name: string | null;
  headline: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  links: ProfileLink[];
  summary: string | null;
  skills: string[];
  roles: ExperienceRole[];
  stories: ExperienceStory[];
  education: Education[];
  created_at: string;
  updated_at: string;
  /** Nothing to score or write from yet. */
  is_empty: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ProposedStory {
  title: string;
  body: string;
  role_id: string | null;
  skills: string[];
}

export interface ChatTurnResponse {
  reply: ChatMessage;
  proposed_stories: ProposedStory[];
}

export interface ImportedExperience {
  full_name: string | null;
  headline: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  summary: string | null;
  skills: string[];
  roles: Array<Omit<ExperienceRole, "id" | "source" | "highlights"> & {
    highlights: Array<{ text: string; sort_order: number }>;
  }>;
  education: Array<Omit<Education, "id">>;
}

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
  /** Whether readable text was extracted. */
  has_text: boolean;
}

export interface MatchSkill {
  skill: string;
  weight: number;
  source: string;
}

export interface PostingMatch {
  /** null when there is no resume, or the posting is too thin to rate. */
  score: number | null;
  rating: string;
  confidence: "high" | "medium" | "none";
  explanation: string;
  matched: MatchSkill[];
  missing: MatchSkill[];
  extra: string[];
  coverage: number | null;
  required_years: number | null;
  resume_years: number | null;
  years_basis: string | null;
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
  /** Present only when the list was fetched with `with_match`. */
  match_score: number | null;
  match_rating: string | null;
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

export type ExportFormat = "docx" | "pdf";

export interface ResumeTemplate {
  id: string;
  name: string;
  is_default: boolean;
  sections: string[];
  options: Record<string, unknown>;
}

export interface ResumeBuildResult {
  document: StoredDocument | null;
  /** The rendered text, so it can be reviewed before downloading. */
  preview: string;
  tailored: boolean;
}

export interface AssistantStatus {
  enabled: boolean;
  model: string;
}
