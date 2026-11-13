export interface Vessel {
  id: number;
  name: string;
  vessel_class: string;
  home_port: string;
  turnaround_hours: number;
}

export interface Task {
  id: number;
  name: string;
  kind: string;
  duration_hours: number;
  vessel_id: number;
  depends_on: number[];
}

export interface Slot {
  task_id: number;
  vessel_id: number;
  start: string;
  end: string;
}

export interface DocumentMeta {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  object_key: string;
  tags: string[];
  uploaded_at: string;
}

export interface Campaign {
  id: number;
  name: string;
  objective: string;
  start_time: string;
  synthetic: boolean;
  makespan_hours: number;
  vessels: Vessel[];
  tasks: Task[];
  schedule: Slot[];
  documents: DocumentMeta[];
}

export interface CampaignSummary {
  id: number;
  name: string;
  start_time: string;
  synthetic: boolean;
  vessel_count: number;
  task_count: number;
  document_count: number;
}

export interface CampaignInput {
  name: string;
  objective: string;
  start_time: string;
  vessels: { key: string; name: string; vessel_class: string; home_port: string; turnaround_hours: number }[];
  tasks: { key: string; name: string; kind: string; duration_hours: number; vessel: string; depends_on: string[] }[];
}

export interface SearchHit {
  document_id: string;
  campaign_id: number;
  campaign_name: string;
  title: string;
  filename: string;
  tags: string[];
  score: number;
  highlight: string | null;
}

export interface SparqlTerm {
  type: string;
  value: string;
  datatype?: string;
}

export interface SparqlResult {
  head: { vars?: string[] };
  results?: { bindings: Record<string, SparqlTerm>[] };
  boolean?: boolean;
}

export interface ConsistencyReport {
  campaign_id: number;
  passed: number;
  failed: number;
  checks: { service: string; name: string; ok: boolean; detail: string }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    let message = text;
    try {
      const detail = JSON.parse(text).detail;
      message = typeof detail === "string" ? detail : JSON.stringify(detail);
    } catch {
      // plain-text error body
    }
    throw new Error(`${res.status}: ${message}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listCampaigns: () => request<CampaignSummary[]>("/api/campaigns"),
  getCampaign: (id: number) => request<Campaign>(`/api/campaigns/${id}`),
  createCampaign: (body: CampaignInput) => request<Campaign>("/api/campaigns", json(body)),
  deleteCampaign: (id: number) => request<void>(`/api/campaigns/${id}`, { method: "DELETE" }),
  loadFixture: () => request<Campaign>("/api/fixture", { method: "POST" }),
  uploadDocument: (id: number, file: File, title: string, tags: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    form.append("tags", tags);
    return request<DocumentMeta>(`/api/campaigns/${id}/documents`, { method: "POST", body: form });
  },
  search: (q: string, campaignId?: number) => {
    const params = new URLSearchParams({ q });
    if (campaignId !== undefined) params.set("campaign_id", String(campaignId));
    return request<SearchHit[]>(`/api/search?${params}`);
  },
  sparql: (query: string) => request<SparqlResult>("/api/sparql", json({ query })),
  consistency: (id: number) => request<ConsistencyReport>(`/api/campaigns/${id}/consistency`),
};
