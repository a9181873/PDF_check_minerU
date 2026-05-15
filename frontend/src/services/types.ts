export enum DiffType {
  TEXT_MODIFIED = 'text_modified',
  NUMBER_MODIFIED = 'number_modified',
  ADDED = 'added',
  DELETED = 'deleted',
  IMAGE_DIFF = 'image_diff',
}

export interface BBox {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface DiffItem {
  id: string;
  diff_type: DiffType;
  old_value: string | null;
  new_value: string | null;
  old_bbox: BBox | null;
  new_bbox: BBox | null;
  old_image_base64?: string | null;
  new_image_base64?: string | null;
  context: string;
  confidence: number;
  reviewed: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface DiffReport {
  project_id: string;
  case_number?: string | null;
  old_filename: string;
  new_filename: string;
  created_at: string;
  total_diffs: number;
  items: DiffItem[];
  summary?: string | null;
}

export enum CheckStatus {
  CONFIRMED = 'confirmed',
  ANOMALY = 'anomaly',
  MISSING = 'missing',
  PENDING = 'pending',
}

export interface ChecklistItem {
  item_id: string;
  check_type: string;
  search_keyword: string;
  expected_old: string | null;
  expected_new: string | null;
  page_hint: number | null;
  status: CheckStatus;
  matched_diff_id: string | null;
  note: string | null;
}

export interface UploadResponse {
  task_id: string;
  status: string;
}

export interface CompareStatusResponse {
  task_id: string;
  status: string;
  progress_percent: number;
  current_step: string;
  error_message: string | null;
}

export interface ReviewActionRequest {
  diff_item_id: string;
  action: string;
  reviewer?: string | null;
  note?: string | null;
}

export interface ReviewSummaryResponse {
  total: number;
  confirmed: number;
  flagged: number;
  pending: number;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface ComparisonInfo {
  id: string;
  project_id: string;
  case_number: string | null;
  old_filename: string;
  new_filename: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  old_markdown_path: string | null;
  new_markdown_path: string | null;
  latest_reviewer: string | null;
  latest_verified_at: string | null;
}

export interface ChecklistImportResponse {
  items_count: number;
  auto_matched_count: number;
}
