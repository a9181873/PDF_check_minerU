import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import {
  DiffReport,
  DiffItem,
  ChecklistItem,
  CompareStatusResponse,
  CheckStatus,
} from '../services/types';

interface CompareState {
  // Current comparison task
  taskId: string | null;
  status: CompareStatusResponse | null;
  report: DiffReport | null;
  
  // Filtered and sorted diff items
  filteredItems: DiffItem[];
  searchQuery: string;
  selectedDiffId: string | null;
  reviewedOnly: boolean;
  
  // Checklist
  checklist: ChecklistItem[];
  checklistFilter: CheckStatus | 'all';
  
  // UI state
  leftPanelHidden: boolean;
  currentPage: { old: number; new: number };
  scrollSyncEnabled: boolean;
  grayscaleEnabled: boolean;
  diffPopupOpen: boolean;
  selectedDiffForPopup: DiffItem | null;
  
  // Actions
  setTaskId: (taskId: string | null) => void;
  setStatus: (status: CompareStatusResponse) => void;
  setReport: (report: DiffReport) => void;
  setSearchQuery: (query: string) => void;
  setSelectedDiffId: (id: string | null) => void;
  toggleReviewedOnly: () => void;
  setChecklist: (checklist: ChecklistItem[]) => void;
  updateChecklistItem: (itemId: string, updates: Partial<ChecklistItem>) => void;
  setChecklistFilter: (filter: CheckStatus | 'all') => void;
  toggleLeftPanel: () => void;
  setCurrentPage: (side: 'old' | 'new', page: number) => void;
  syncPages: (page: number) => void;
  setScrollSyncEnabled: (enabled: boolean) => void;
  setGrayscaleEnabled: (enabled: boolean) => void;
  openDiffPopup: (diff: DiffItem) => void;
  closeDiffPopup: () => void;
  confirmDiff: (diffId: string, reviewer?: string | null, reviewedAt?: string | null) => Promise<void>;
  flagDiff: (diffId: string, reviewer?: string | null, reviewedAt?: string | null) => Promise<void>;
  
  // Computed
  getFilteredChecklist: () => ChecklistItem[];
  getDiffById: (id: string) => DiffItem | undefined;
  getStats: () => {
    total: number;
    reviewed: number;
    pending: number;
    added: number;
    deleted: number;
    modified: number;
    flagged: number;
    visual: number;
  };
  
  // View controls
  scale: number;
  setScale: (scale: number) => void;
}

function filterDiffItems(items: DiffItem[], searchQuery: string, reviewedOnly: boolean): DiffItem[] {
  const query = searchQuery.trim().toLowerCase();
  return items.filter((item) => {
    const matchesSearch = query === '' ||
      item.old_value?.toLowerCase().includes(query) ||
      item.new_value?.toLowerCase().includes(query) ||
      item.context?.toLowerCase().includes(query) ||
      item.id.toLowerCase().includes(query) ||
      (item.reviewed_by || '').toLowerCase().includes(query);
    const matchesReviewed = !reviewedOnly || !item.reviewed;
    return Boolean(matchesSearch && matchesReviewed);
  });
}

export function calculateDiffStats(items: DiffItem[]) {
  const stats = items.reduce(
    (result, item) => {
      result.total += 1;
      if (item.reviewed) result.reviewed += 1;
      if (item.diff_type === 'added') result.added += 1;
      if (item.diff_type === 'deleted') result.deleted += 1;
      if (item.diff_type === 'text_modified' || item.diff_type === 'number_modified') result.modified += 1;
      if (item.flagged) result.flagged += 1;
      if (item.diff_type === 'image_diff') result.visual += 1;
      return result;
    },
    { total: 0, reviewed: 0, added: 0, deleted: 0, modified: 0, flagged: 0, visual: 0 }
  );
  return { ...stats, pending: stats.total - stats.reviewed };
}

export const useCompareStore = create<CompareState>()(
  devtools(
    (set, get) => ({
      taskId: null,
      status: null,
      report: null,
      filteredItems: [],
      searchQuery: '',
      selectedDiffId: null,
      reviewedOnly: false,
      checklist: [],
      checklistFilter: 'all',
      leftPanelHidden: false,
      currentPage: { old: 1, new: 1 },
      scrollSyncEnabled: true,
      grayscaleEnabled: true,
      diffPopupOpen: false,
      selectedDiffForPopup: null,
      scale: 1.0,

      setTaskId: (taskId) => {
        if (get().taskId === taskId) {
          return;
        }

        set({
          taskId,
          status: null,
          report: null,
          filteredItems: [],
          searchQuery: '',
          selectedDiffId: null,
          reviewedOnly: false,
          checklist: [],
          checklistFilter: 'all',
          currentPage: { old: 1, new: 1 },
          diffPopupOpen: false,
          selectedDiffForPopup: null,
        });
      },

      setScale: (scale) => set({ scale }),

      setStatus: (status) => set({ status }),

      setReport: (report) => {
        const items = report.items || [];
        const { reviewedOnly, searchQuery, selectedDiffId } = get();
        // Preserve existing selection if it's still valid in the new report
        const selectionStillValid = selectedDiffId && items.some((i) => i.id === selectedDiffId);
        set({
          report,
          filteredItems: filterDiffItems(items, searchQuery, reviewedOnly),
          selectedDiffId: selectionStillValid ? selectedDiffId : (items.length > 0 ? items[0].id : null),
        });
      },

      setSearchQuery: (query) => {
        const { report, reviewedOnly } = get();
        if (!report) return;
        set({
          searchQuery: query,
          filteredItems: filterDiffItems(report.items, query, reviewedOnly),
        });
      },

      setSelectedDiffId: (id) => set({ selectedDiffId: id }),

      toggleReviewedOnly: () => {
        const { reviewedOnly, report, searchQuery } = get();
        const newReviewedOnly = !reviewedOnly;
        if (!report) return;
        set({
          reviewedOnly: newReviewedOnly,
          filteredItems: filterDiffItems(report.items, searchQuery, newReviewedOnly),
        });
      },

      setChecklist: (checklist) => set({ checklist }),

      updateChecklistItem: (itemId, updates) => {
        const { checklist } = get();
        const updated = checklist.map(item =>
          item.item_id === itemId ? { ...item, ...updates } : item
        );
        set({ checklist: updated });
      },

      setChecklistFilter: (filter) => set({ checklistFilter: filter }),

      toggleLeftPanel: () => {
        const { leftPanelHidden } = get();
        set({ leftPanelHidden: !leftPanelHidden });
      },

      setCurrentPage: (side, page) => {
        const { currentPage, scrollSyncEnabled } = get();
        const newPage = { ...currentPage, [side]: page };
        
        if (scrollSyncEnabled && side === 'old') {
          newPage.new = page;
        } else if (scrollSyncEnabled && side === 'new') {
          newPage.old = page;
        }
        
        set({ currentPage: newPage });
      },

      syncPages: (page) => {
        set({ currentPage: { old: page, new: page } });
      },

      setScrollSyncEnabled: (enabled) => set({ scrollSyncEnabled: enabled }),

      setGrayscaleEnabled: (enabled) => set({ grayscaleEnabled: enabled }),

      openDiffPopup: (diff) => set({ diffPopupOpen: true, selectedDiffForPopup: diff }),

      closeDiffPopup: () => set({ diffPopupOpen: false, selectedDiffForPopup: null }),

      confirmDiff: async (diffId, reviewer, reviewedAt) => {
        const { taskId, report, searchQuery, reviewedOnly } = get();
        if (!taskId || !report) return;

        const updatedItems = report.items.map(item =>
          item.id === diffId
            ? { ...item, reviewed: true, flagged: false, reviewed_by: reviewer || null, reviewed_at: reviewedAt || new Date().toISOString() }
            : item
        );
        const updatedReport = { ...report, items: updatedItems };
        set({
          report: updatedReport,
          filteredItems: filterDiffItems(updatedItems, searchQuery, reviewedOnly),
        });
      },

      flagDiff: async (diffId, reviewer, reviewedAt) => {
        const { taskId, report, searchQuery, reviewedOnly } = get();
        if (!taskId || !report) return;

        const updatedItems = report.items.map(item =>
          item.id === diffId
            ? { ...item, reviewed: true, flagged: true, reviewed_by: reviewer || null, reviewed_at: reviewedAt || new Date().toISOString() }
            : item
        );
        const updatedReport = { ...report, items: updatedItems };
        set({
          report: updatedReport,
          filteredItems: filterDiffItems(updatedItems, searchQuery, reviewedOnly),
        });
      },

      getFilteredChecklist: () => {
        const { checklist, checklistFilter } = get();
        if (checklistFilter === 'all') return checklist;
        return checklist.filter(item => item.status === checklistFilter);
      },

      getDiffById: (id) => {
        const { report } = get();
        return report?.items.find(item => item.id === id);
      },

      getStats: () => {
        const { report } = get();
        return calculateDiffStats(report?.items || []);
      },
    }),
    { name: 'compare-store' }
  )
);
