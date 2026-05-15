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
  confirmDiff: (diffId: string, reviewer?: string, note?: string) => Promise<void>;
  flagDiff: (diffId: string, reviewer?: string, note?: string) => Promise<void>;
  
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
  };
  
  // View controls
  scale: number;
  setScale: (scale: number) => void;
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
        const { selectedDiffId } = get();
        // Preserve existing selection if it's still valid in the new report
        const selectionStillValid = selectedDiffId && items.some((i) => i.id === selectedDiffId);
        set({
          report,
          filteredItems: items,
          selectedDiffId: selectionStillValid ? selectedDiffId : (items.length > 0 ? items[0].id : null),
        });
      },

      setSearchQuery: (query) => {
        const { report, reviewedOnly } = get();
        if (!report) return;
        
        const items = report.items.filter(item => {
          const matchesSearch = query === '' || 
            item.old_value?.toLowerCase().includes(query.toLowerCase()) ||
            item.new_value?.toLowerCase().includes(query.toLowerCase()) ||
            item.context?.toLowerCase().includes(query.toLowerCase()) ||
            item.id.toLowerCase().includes(query.toLowerCase()) ||
            (item.reviewed_by || '').toLowerCase().includes(query.toLowerCase());
          
          const matchesReviewed = !reviewedOnly || !item.reviewed;
          
          return matchesSearch && matchesReviewed;
        });
        
        set({ searchQuery: query, filteredItems: items });
      },

      setSelectedDiffId: (id) => set({ selectedDiffId: id }),

      toggleReviewedOnly: () => {
        const { reviewedOnly, report, searchQuery } = get();
        const newReviewedOnly = !reviewedOnly;
        
        if (!report) return;
        
        const items = report.items.filter(item => {
          const matchesSearch = searchQuery === '' || 
            item.old_value?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.new_value?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.context?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (item.reviewed_by || '').toLowerCase().includes(searchQuery.toLowerCase());
          
          const matchesReviewed = !newReviewedOnly || !item.reviewed;
          
          return matchesSearch && matchesReviewed;
        });
        
        set({ reviewedOnly: newReviewedOnly, filteredItems: items });
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

      confirmDiff: async (diffId, reviewer, note) => {
        void note;
        const { taskId, report, searchQuery, reviewedOnly } = get();
        if (!taskId || !report) return;

        const updatedItems = report.items.map(item =>
          item.id === diffId
            ? { ...item, reviewed: true, reviewed_by: reviewer || null, reviewed_at: new Date().toISOString() }
            : item
        );
        const updatedReport = { ...report, items: updatedItems };
        const filtered = updatedItems.filter(item => {
          const matchesSearch = searchQuery === '' ||
            item.old_value?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.new_value?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.context?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (item.reviewed_by || '').toLowerCase().includes(searchQuery.toLowerCase());
          const matchesReviewed = !reviewedOnly || !item.reviewed;
          return matchesSearch && matchesReviewed;
        });
        set({ report: updatedReport, filteredItems: filtered });
      },

      flagDiff: async (diffId, reviewer, note) => {
        void note;
        const { taskId, report, searchQuery, reviewedOnly } = get();
        if (!taskId || !report) return;

        const updatedItems = report.items.map(item =>
          item.id === diffId
            ? { ...item, reviewed: true, reviewed_by: reviewer || null, reviewed_at: new Date().toISOString() }
            : item
        );
        const updatedReport = { ...report, items: updatedItems };
        const filtered = updatedItems.filter(item => {
          const matchesSearch = searchQuery === '' ||
            item.old_value?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.new_value?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.context?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            item.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (item.reviewed_by || '').toLowerCase().includes(searchQuery.toLowerCase());
          const matchesReviewed = !reviewedOnly || !item.reviewed;
          return matchesSearch && matchesReviewed;
        });
        set({ report: updatedReport, filteredItems: filtered });
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
        if (!report) {
          return { total: 0, reviewed: 0, pending: 0, added: 0, deleted: 0, modified: 0 };
        }
        
        const items = report.items;
        const total = items.length;
        const reviewed = items.filter(item => item.reviewed).length;
        const pending = total - reviewed;
        const added = items.filter(item => item.diff_type === 'added').length;
        const deleted = items.filter(item => item.diff_type === 'deleted').length;
        const modified = items.filter(item => 
          item.diff_type === 'text_modified' || item.diff_type === 'number_modified'
        ).length;
        
        return { total, reviewed, pending, added, deleted, modified };
      },
    }),
    { name: 'compare-store' }
  )
);
