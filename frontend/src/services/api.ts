import axios from 'axios';
import {
  UploadResponse,
  CompareStatusResponse,
  DiffReport,
  ReviewSummaryResponse,
  ChecklistItem,
  ChecklistImportResponse,
  Project,
  ComparisonInfo,
  ReviewActionRequest,
} from './types';

const normalizeBase = (value?: string) => (value ? value.replace(/\/+$/, '') : '');
const joinUrl = (base: string, path: string) => `${base}${path.startsWith('/') ? path : `/${path}`}`;

const API_BASE = normalizeBase(import.meta.env.VITE_API_BASE);
const WS_BASE = normalizeBase(import.meta.env.VITE_WS_BASE);

const api = axios.create({
  baseURL: API_BASE || undefined,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const buildApiUrl = (path: string) => (API_BASE ? joinUrl(API_BASE, path) : path);

/**
 * Like buildApiUrl, but appends ?token= for endpoints opened via window.open / <iframe>
 * (browser-driven loads that can't set the Authorization header).
 */
export const buildAuthedUrl = (path: string) => {
  const base = buildApiUrl(path);
  const token = localStorage.getItem('auth_token');
  if (!token) return base;
  const sep = base.includes('?') ? '&' : '?';
  return `${base}${sep}token=${encodeURIComponent(token)}`;
};

export const buildWebSocketUrl = (path: string) => {
  const baseOrigin = WS_BASE || API_BASE || window.location.origin;
  const url = new URL(path, `${baseOrigin}/`);

  if (url.protocol === 'http:') {
    url.protocol = 'ws:';
  } else if (url.protocol === 'https:') {
    url.protocol = 'wss:';
  }

  const token = localStorage.getItem('auth_token');
  if (token) {
    url.searchParams.set('token', token);
  }

  return url.toString();
};

export const compareApi = {
  // Upload PDF files for comparison
  async uploadFiles(
    oldFile: File,
    newFile: File,
    projectId?: string,
    caseNumber?: string
  ): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('old_pdf', oldFile);
    formData.append('new_pdf', newFile);
    if (caseNumber) {
      formData.append('case_number', caseNumber);
    }
    if (projectId) {
      formData.append('project_id', projectId);
    }

    const response = await api.post<UploadResponse>('/api/compare/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  // Get comparison status
  async getStatus(taskId: string): Promise<CompareStatusResponse> {
    const response = await api.get<CompareStatusResponse>(`/api/compare/${taskId}/status`);
    return response.data;
  },

  // Get comparison result (diff report)
  async getResult(taskId: string): Promise<DiffReport> {
    const response = await api.get<DiffReport>(`/api/compare/${taskId}/result`);
    return response.data;
  },

  // Get markdown manifest
  async getMarkdownManifest(taskId: string) {
    const response = await api.get(`/api/compare/${taskId}/markdown`);
    return response.data;
  },

  // Download markdown file
  async downloadMarkdown(taskId: string, version: 'old' | 'new') {
    const response = await api.get(`/api/compare/${taskId}/markdown/${version}`, {
      responseType: 'blob',
    });
    return response.data;
  },
};

export const projectApi = {
  // List all projects
  async listProjects(): Promise<Project[]> {
    const response = await api.get('/api/projects');
    return response.data;
  },

  // Create a new project
  async createProject(name: string): Promise<Project> {
    const response = await api.post('/api/projects', { name });
    return response.data;
  },

  // List comparisons for a project
  async listProjectComparisons(projectId: string): Promise<ComparisonInfo[]> {
    const response = await api.get(`/api/projects/${projectId}/comparisons`);
    return response.data;
  },

  // List all recent comparisons globally
  async listAllComparisons(limit: number = 10): Promise<ComparisonInfo[]> {
    const response = await api.get(`/api/projects/all/comparisons`, { params: { limit } });
    return response.data;
  },

  async deleteComparison(comparisonId: string): Promise<{ ok: boolean }> {
    const response = await api.delete(`/api/projects/all/comparisons/${comparisonId}`);
    return response.data;
  },

  exportAllComparisonsUrl(): string {
    return buildAuthedUrl('/api/projects/all/comparisons/export');
  },
};

export const reviewApi = {
  // Confirm or flag a diff item
  async confirmDiff(
    comparisonId: string,
    payload: ReviewActionRequest
  ): Promise<{ ok: boolean }> {
    const response = await api.post(`/api/review/${comparisonId}/confirm`, payload);
    return response.data;
  },

  // Get review summary
  async getSummary(comparisonId: string): Promise<ReviewSummaryResponse> {
    const response = await api.get<ReviewSummaryResponse>(`/api/review/${comparisonId}/summary`);
    return response.data;
  },
};

export const checklistApi = {
  // Import checklist from CSV/Excel
  async importChecklist(
    comparisonId: string,
    file: File
  ): Promise<ChecklistImportResponse> {
    const formData = new FormData();
    formData.append('checklist_csv', file);

    const response = await api.post<ChecklistImportResponse>(
      `/api/checklist/${comparisonId}/import`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
    return response.data;
  },

  // Get checklist items
  async getChecklist(comparisonId: string): Promise<ChecklistItem[]> {
    const response = await api.get<ChecklistItem[]>(`/api/checklist/${comparisonId}`);
    return response.data;
  },

  // Update checklist item status
  async updateChecklistItem(
    comparisonId: string,
    itemId: string,
    updates: Partial<ChecklistItem>
  ): Promise<{ ok: boolean }> {
    const response = await api.patch(`/api/checklist/${comparisonId}/${itemId}`, updates);
    return response.data;
  },
};

export const exportApi = {
  getDownloadUrl(comparisonId: string, format: 'report' | 'pdf' | 'excel' = 'report') {
    return buildAuthedUrl(`/api/export/${comparisonId}/${format}`);
  },
};

export const archiveApi = {
  async verify(
    comparisonId: string,
    data: { reviewer?: string; notes?: string }
  ): Promise<{ archive_id: string; session_id: string; is_new_archive: boolean; verified_at: string }> {
    const response = await api.post(`/api/archive/${comparisonId}/verify`, data);
    return response.data;
  },

  async getHistory(
    comparisonId: string
  ): Promise<{ archive: ArchiveRecord | null; sessions: VerificationSession[]; review_logs: ReviewLogChange[] }> {
    const response = await api.get(`/api/archive/${comparisonId}/history`);
    return response.data;
  },

  getFileUrl(archiveId: string, fileType: 'old_pdf' | 'new_pdf' | 'annotated_pdf'): string {
    return buildAuthedUrl(`/api/archive/files/${archiveId}/${fileType}`);
  },
};

export interface ArchiveRecord {
  id: string;
  old_hash: string;
  new_hash: string;
  case_number: string | null;
  old_filename: string;
  new_filename: string;
  old_archive_path: string;
  new_archive_path: string;
  annotated_archive_path: string | null;
  first_comparison_id: string;
  archived_at: string;
}

export interface VerificationSession {
  id: string;
  archive_id: string;
  comparison_id: string;
  case_number: string | null;
  reviewer: string | null;
  verified_at: string;
  total_diffs: number;
  confirmed: number;
  flagged: number;
  notes: string | null;
  review_logs_json?: string | null;
}

export interface ReviewLogChange {
  id: string;
  comparison_id: string;
  diff_item_id: string;
  action: string;
  reviewer: string | null;
  note: string | null;
  created_at: string;
  previous_action: string | null;
  previous_reviewer: string | null;
  previous_note: string | null;
  change_type: 'created' | 'modified';
  change_summary: string;
}

export default api;
