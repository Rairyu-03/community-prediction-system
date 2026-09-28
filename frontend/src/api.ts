import type { Community, CommunityImportReport, Dashboard, ParameterSet, PredictionResultRow, PredictionRun, Project, QualityReport } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export type ApiOptions = {
  baseUrl?: string;
  token?: string;
  hostContext?: Record<string, unknown>;
};

function downloadFilename(response: Response, url: string): string {
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try { return decodeURIComponent(encoded.replace(/^"|"$/g, "")); } catch { /* fall through */ }
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  if (plain) return plain;
  try { return decodeURIComponent(new URL(url, window.location.href).pathname.split("/").filter(Boolean).at(-1) || "download"); }
  catch { return "download"; }
}

/** Download through fetch so a file response never navigates away from the SPA. */
export async function downloadFile(url: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) {
    let message = `下载失败（${response.status}）`;
    try { const body = await response.json(); message = body.detail || message; } catch { /* keep status message */ }
    throw new Error(message);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = downloadFilename(response, url);
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export class CommunityApi {
  private baseUrl: string;
  private token?: string;
  private hostContext?: Record<string, unknown>;

  constructor(options: ApiOptions = {}) {
    this.baseUrl = (options.baseUrl || import.meta.env.VITE_API_BASE || "/api").replace(/\/$/, "");
    this.token = options.token;
    this.hostContext = options.hostContext;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    if (this.hostContext) headers.set("X-Host-Context", JSON.stringify(this.hostContext));
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers });
    if (!response.ok) {
      let message = `请求失败（${response.status}）`;
      try {
        const body = await response.json();
        message = Array.isArray(body.detail)
          ? body.detail.map((item: { loc?: Array<string | number>; msg?: string }) => `${item.loc?.slice(1).join(".") || "输入数据"}：${item.msg || "校验失败"}`).join("；")
          : typeof body.detail === "string" ? body.detail : message;
      } catch {
        message = response.statusText || message;
      }
      throw new ApiError(response.status, message);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  health() {
    return this.request<{ status: string; service: string; version: string }>("/health");
  }

  listProjects() {
    return this.request<Project[]>("/projects");
  }

  createProject(name: string) {
    return this.request<Project>("/projects", { method: "POST", body: JSON.stringify({ name }) });
  }

  renameProject(projectId: number, name: string) {
    return this.request<Project>(`/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
  }

  deleteProject(projectId: number) {
    return this.request<void>(`/projects/${projectId}`, { method: "DELETE" });
  }

  projectExportUrl(projectId:number) { const token=this.token?`?access_token=${encodeURIComponent(this.token)}`:""; return `${this.baseUrl}/projects/${projectId}/export${token}`; }
  systemBackupUrl() { const token=this.token?`?access_token=${encodeURIComponent(this.token)}`:""; return `${this.baseUrl}/system/backup${token}`; }
  importProjectArchive(file:File) { const form=new FormData();form.append("file",file);return this.request<Project>("/projects/import-archive",{method:"POST",body:form}); }
  restoreSystem(file:File) { const form=new FormData();form.append("file",file);return this.request<{restoredCount:number;projects:Project[]}>("/system/restore",{method:"POST",body:form}); }
  storageInfo() { return this.request<{dataRoot:string;database:string;projects:string;portable:boolean}>("/storage-info"); }
  quality(projectId:number,kind:"population"|"facility") { return this.request<QualityReport>(`/projects/${projectId}/quality?kind=${kind}`); }

  getParameters(projectId: number, kind: "population" | "facility") {
    return this.request<ParameterSet>(`/projects/${projectId}/parameters/${kind}`);
  }

  saveParameters(projectId: number, kind: "population" | "facility", data: Record<string, unknown>) {
    return this.request<ParameterSet>(`/projects/${projectId}/parameters/${kind}`, {
      method: "PUT",
      body: JSON.stringify({ data }),
    });
  }

  importParameters(projectId: number, kind: "population" | "facility", file: File) {
    const form = new FormData();
    form.append("file", file);
    return this.request<ParameterSet>(`/projects/${projectId}/parameters/${kind}/import`, {
      method: "POST",
      body: form,
    });
  }

  listCommunities(projectId: number, query = "") {
    return this.request<Community[]>(`/projects/${projectId}/communities?q=${encodeURIComponent(query)}`);
  }

  createCommunity(projectId: number, payload: Partial<Community>) {
    return this.request<Community>(`/projects/${projectId}/communities`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  updateCommunity(projectId: number, communityId: number, payload: Partial<Community>) {
    return this.request<Community>(`/projects/${projectId}/communities/${communityId}`, { method: "PUT", body: JSON.stringify(payload) });
  }

  clearRuns(projectId: number, runIds: number[]) {
    return this.request<{deleted_count: number}>(`/projects/${projectId}/runs/clear`, { method: "POST", body: JSON.stringify(runIds) });
  }

  importCommunity(projectId: number, file: File) {
    const form = new FormData();
    form.append("file", file);
    return this.request<CommunityImportReport>(`/projects/${projectId}/communities/import`, {
      method: "POST",
      body: form,
    });
  }

  communityTemplateUrl(projectId: number, communityId?: number, blank = false) {
    const query = new URLSearchParams();
    if (this.token) query.set("access_token", this.token);
    if (communityId) query.set("community_id", String(communityId));
    if (blank) query.set("blank", "true");
    return `${this.baseUrl}/projects/${projectId}/communities/template?${query}`;
  }

  getCalculation(runId: number, communityId: number, year: number) {
    return this.request<import("./CalculationPanel").Calculation>(`/runs/${runId}/calculation?community_id=${communityId}&year=${year}`);
  }

  deleteCommunity(projectId: number, communityId: number) {
    return this.request<void>(`/projects/${projectId}/communities/${communityId}`, { method: "DELETE" });
  }

  dashboard(projectId: number) {
    return this.request<Dashboard>(`/projects/${projectId}/dashboard`);
  }

  runPopulation(projectId: number, seed = 20260825) {
    return this.request<PredictionRun>(`/projects/${projectId}/predictions/population`, {
      method: "POST",
      body: JSON.stringify({ seed }),
    });
  }

  runFacility(projectId: number) {
    return this.request<PredictionRun>(`/projects/${projectId}/predictions/facility`, {
      method: "POST",
      body: JSON.stringify({
        seed: 20260825,
        generate_report: false,
      }),
    });
  }

  generateReport(runId: number, reportMode: "community" | "overall", communityId?: number) {
    return this.request<{ run_id: number; filename: string; report_available: boolean }>(`/runs/${runId}/report`, {
      method: "POST",
      body: JSON.stringify({ report_mode: reportMode, community_id: communityId }),
    });
  }

  parameterTemplateUrl(projectId: number, kind: "population" | "facility") {
    const token = this.token ? `?access_token=${encodeURIComponent(this.token)}` : "";
    return `${this.baseUrl}/projects/${projectId}/parameters/${kind}/template${token}`;
  }

  listRuns(projectId: number) {
    return this.request<PredictionRun[]>(`/projects/${projectId}/runs`);
  }

  getRunResults(runId: number) {
    return this.request<PredictionResultRow[]>(`/runs/${runId}/results`);
  }

  downloadUrl(runId: number) {
    const token = this.token ? `?access_token=${encodeURIComponent(this.token)}` : "";
    return `${this.baseUrl}/runs/${runId}/download${token}`;
  }

  reportUrl(runId: number) {
    const token = this.token ? `?access_token=${encodeURIComponent(this.token)}` : "";
    return `${this.baseUrl}/runs/${runId}/report${token}`;
  }

  backupUrl(runId: number) {
    const token = this.token ? `?access_token=${encodeURIComponent(this.token)}` : "";
    return `${this.baseUrl}/runs/${runId}/backup${token}`;
  }

  deleteRun(runId: number) {
    return this.request<void>(`/runs/${runId}`, { method: "DELETE" });
  }
}
