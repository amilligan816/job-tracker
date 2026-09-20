import type {
  Application,
  ApplicationDetail,
  ApplicationEvent,
  ApplicationStatus,
  AssistantRun,
  AssistantStatus,
  Company,
  DocumentKind,
  JobPosting,
  PipelineSummary,
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
    list: (params: { status?: ApplicationStatus[]; due_before?: string } = {}) =>
      request<Application[]>(`/applications${qs(params)}`),
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
    addEvent: (id: string, body: Record<string, unknown>) =>
      request<ApplicationEvent>(`/applications/${id}/events`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  documents: {
    list: (params: { application_id?: string; kind?: DocumentKind } = {}) =>
      request<StoredDocument[]>(`/documents${qs(params)}`),
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

  assistant: {
    status: () => request<AssistantStatus>("/assistant/status"),
    runs: (applicationId?: string) =>
      request<AssistantRun[]>(`/assistant/runs${qs({ application_id: applicationId })}`),
    matchAnalysis: (body: { application_id: string; resume_document_id?: string }) =>
      request<AssistantRun>("/assistant/match-analysis", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    coverLetter: (body: {
      application_id: string;
      resume_document_id?: string;
      tone?: string;
      emphasis?: string;
    }) =>
      request<AssistantRun>("/assistant/cover-letter", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    interviewPrep: (body: {
      application_id: string;
      resume_document_id?: string;
      round_type?: string;
    }) =>
      request<AssistantRun>("/assistant/interview-prep", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },
};
