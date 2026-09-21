import type {
  Application,
  ApplicationDetail,
  ApplicationEvent,
  ApplicationStatus,
  AssistantRun,
  AssistantStatus,
  Company,
  DocumentKind,
  ChatMessage,
  ChatTurnResponse,
  Education,
  ExperienceProfile,
  ExperienceRole,
  ExperienceStory,
  ExportFormat,
  Highlight,
  ImportedExperience,
  ResumeBuildResult,
  ResumeTemplate,
  JobPosting,
  PipelineSummary,
  PostingMatch,
  StoredDocument,
} from "./types";

const BASE = `${import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"}/api`;

/** An API error carrying the backend's `detail`, so the UI can show it verbatim. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init.headers
        : { "content-type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      // FastAPI validation errors arrive as a list of objects.
      detail = Array.isArray(body.detail)
        ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
        : (body.detail ?? detail);
    } catch {
      /* non-JSON error body; keep the status text */
    }
    throw new ApiError(detail, response.status);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const qs = (params: Record<string, unknown>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)));
    else search.append(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
};

export const api = {
  companies: {
    list: (q?: string) => request<Company[]>(`/companies${qs({ q })}`),
    create: (body: Partial<Company>) =>
      request<Company>("/companies", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Partial<Company>) =>
      request<Company>(`/companies/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (id: string) => request<void>(`/companies/${id}`, { method: "DELETE" }),
  },

  postings: {
    list: (params: { company_id?: string; q?: string } = {}) =>
      request<JobPosting[]>(`/postings${qs(params)}`),
    get: (id: string) => request<JobPosting>(`/postings/${id}`),
    create: (body: Record<string, unknown>) =>
      request<JobPosting>("/postings", { method: "POST", body: JSON.stringify(body) }),
    capture: (body: { url?: string; text?: string; parse: boolean }) =>
      request<JobPosting>("/postings/capture", { method: "POST", body: JSON.stringify(body) }),
    reparse: (id: string) => request<JobPosting>(`/postings/${id}/reparse`, { method: "POST" }),
    update: (id: string, body: Record<string, unknown>) =>
      request<JobPosting>(`/postings/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (id: string) => request<void>(`/postings/${id}`, { method: "DELETE" }),
  },

  applications: {
    list: (
      params: {
        status?: ApplicationStatus[];
        due_before?: string;
        with_match?: boolean;
      } = {},
    ) => request<Application[]>(`/applications${qs(params)}`),
    summary: () => request<PipelineSummary>("/applications/summary"),
    get: (id: string) => request<ApplicationDetail>(`/applications/${id}`),
    create: (body: Record<string, unknown>) =>
      request<ApplicationDetail>("/applications", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Record<string, unknown>) =>
      request<ApplicationDetail>(`/applications/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    remove: (id: string) => request<void>(`/applications/${id}`, { method: "DELETE" }),
    match: (id: string, resumeDocumentId?: string) =>
      request<PostingMatch>(
        `/applications/${id}/match${qs({ resume_document_id: resumeDocumentId })}`,
      ),
    addEvent: (id: string, body: Record<string, unknown>) =>
      request<ApplicationEvent>(`/applications/${id}/events`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  documents: {
    list: (
      params: { application_id?: string; kind?: DocumentKind } = {},
    ) => request<StoredDocument[]>(`/documents${qs(params)}`),
    upload: (file: File, kind: DocumentKind, applicationId?: string) => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      if (applicationId) form.append("application_id", applicationId);
      return request<StoredDocument>("/documents", { method: "POST", body: form });
    },
    downloadUrl: (id: string) =>
      request<{ url: string; expires_in: number }>(`/documents/${id}/download`),
    remove: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  },

  experience: {
    get: () => request<ExperienceProfile>("/experience"),
    update: (body: Record<string, unknown>) =>
      request<ExperienceProfile>("/experience", { method: "PATCH", body: JSON.stringify(body) }),
    /** The plain text the matcher scores and the assistant is grounded in. */
    text: () => request<{ text: string; is_empty: boolean }>("/experience/text"),

    createRole: (body: Record<string, unknown>) =>
      request<ExperienceRole>("/experience/roles", { method: "POST", body: JSON.stringify(body) }),
    updateRole: (id: string, body: Record<string, unknown>) =>
      request<ExperienceRole>(`/experience/roles/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    removeRole: (id: string) => request<void>(`/experience/roles/${id}`, { method: "DELETE" }),

    addHighlight: (roleId: string, text: string, sortOrder = 0) =>
      request<Highlight>(`/experience/roles/${roleId}/highlights`, {
        method: "POST",
        body: JSON.stringify({ text, sort_order: sortOrder }),
      }),
    updateHighlight: (id: string, body: Record<string, unknown>) =>
      request<Highlight>(`/experience/highlights/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    removeHighlight: (id: string) =>
      request<void>(`/experience/highlights/${id}`, { method: "DELETE" }),

    createStory: (body: Record<string, unknown>) =>
      request<ExperienceStory>("/experience/stories", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    updateStory: (id: string, body: Record<string, unknown>) =>
      request<ExperienceStory>(`/experience/stories/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    removeStory: (id: string) => request<void>(`/experience/stories/${id}`, { method: "DELETE" }),

    importResume: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return request<ImportedExperience>("/experience/import", { method: "POST", body: form });
    },
    applyImport: (body: ImportedExperience) =>
      request<ExperienceProfile>("/experience/import/apply", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    chat: () => request<ChatMessage[]>("/experience/chat"),
    sendChat: (message: string) =>
      request<ChatTurnResponse>("/experience/chat", {
        method: "POST",
        body: JSON.stringify({ message }),
      }),
    clearChat: () => request<void>("/experience/chat", { method: "DELETE" }),

    createEducation: (body: Record<string, unknown>) =>
      request<Education>("/experience/education", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    removeEducation: (id: string) =>
      request<void>(`/experience/education/${id}`, { method: "DELETE" }),
  },

  resumes: {
    templates: () => request<ResumeTemplate[]>("/resumes/templates"),
    build: (body: {
      application_id: string;
      template_id?: string;
      tailor: boolean;
      export_format?: ExportFormat;
    }) => request<ResumeBuildResult>("/resumes/build", { method: "POST", body: JSON.stringify(body) }),
  },

  assistant: {
    status: () => request<AssistantStatus>("/assistant/status"),
    runs: (applicationId?: string) =>
      request<AssistantRun[]>(`/assistant/runs${qs({ application_id: applicationId })}`),
    /** Renders a run to Word or PDF and files it under Documents. */
    exportRun: (runId: string, format: ExportFormat) =>
      request<StoredDocument>(`/assistant/runs/${runId}/export${qs({ format })}`, {
        method: "POST",
      }),
    matchAnalysis: (body: { application_id: string }) =>
      request<AssistantRun>("/assistant/match-analysis", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    coverLetter: (body: { application_id: string; tone?: string; emphasis?: string }) =>
      request<AssistantRun>("/assistant/cover-letter", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    interviewPrep: (body: { application_id: string; round_type?: string }) =>
      request<AssistantRun>("/assistant/interview-prep", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },
};
