import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { isAxiosError } from 'axios';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertCircle, BarChart3, ChevronDown, ClipboardList, Download, Eye, EyeOff, LogOut, Save, Settings, Upload, ZoomIn, ZoomOut } from 'lucide-react';

import ChecklistPanel from '../components/ChecklistPanel';
import DiffListPanel from '../components/DiffListPanel';
import SearchBar from '../components/SearchBar';
import SyncScrollContainer from '../components/SyncScrollContainer';
import VerificationHistoryModal from '../components/VerificationHistoryModal';
import { checklistApi, buildApiUrl, buildWebSocketUrl, compareApi, reviewApi, archiveApi } from '../services/api';
import { ChecklistItem, DiffReport } from '../services/types';
import { useCompareStore } from '../stores/compareStore';
import { useCrossWindowSync } from '../hooks/useCrossWindowSync';
import { useAuthStore } from '../stores/authStore';

const ChecklistUpload = lazy(() => import('../components/ChecklistUpload'));
const DiffPopup = lazy(() => import('../components/DiffPopup'));
const PDFViewer = lazy(() => import('../components/PDFViewer'));

type WsMessage =
  | {
      event: 'progress';
      data?: {
        status?: string;
        step?: string;
        percent?: number;
        error_message?: string | null;
      };
    }
  | {
      event: 'complete';
      data?: DiffReport | string;
    }
  | {
      event: 'error';
      data?: {
        message?: string;
      };
    };

function InlineLoader({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-[320px] items-center justify-center rounded-[28px] bg-[linear-gradient(180deg,_rgba(255,255,255,0.96)_0%,_rgba(245,245,245,0.96)_100%)]">
      <div className="text-center">
        <div className="mx-auto mb-4 h-10 w-10 rounded-full border-4 border-primary-600 border-t-transparent animate-spin" />
        <p className="text-sm uppercase tracking-[0.18em] text-primary-700">{label}</p>
      </div>
    </div>
  );
}

const ComparePage: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const wsConnectionRef = useRef<WebSocket | null>(null);
  const exportMenuRef = useRef<HTMLDivElement | null>(null);

  const {
    status,
    report,
    filteredItems,
    searchQuery,
    selectedDiffId,
    reviewedOnly,
    checklist,
    leftPanelHidden,
    currentPage,
    scrollSyncEnabled,
    grayscaleEnabled,
    diffPopupOpen,
    selectedDiffForPopup,
    setTaskId,
    setStatus,
    setReport,
    setSearchQuery,
    setSelectedDiffId,
    toggleReviewedOnly,
    setChecklist,
    updateChecklistItem,
    toggleLeftPanel,
    setCurrentPage,
    setScrollSyncEnabled,
    setGrayscaleEnabled,
    scale,
    setScale,
    openDiffPopup,
    closeDiffPopup,
    confirmDiff: storeConfirmDiff,
    flagDiff: storeFlagDiff,
    getStats,
  } = useCompareStore();

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showChecklistUpload, setShowChecklistUpload] = useState(false);
  const [leftTab, setLeftTab] = useState<'diff_list' | 'checklist'>('diff_list');
  const [activeTab, setActiveTab] = useState<'diffs' | 'checklist'>('diffs');
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showDiffLabels, setShowDiffLabels] = useState(true);
  const [archiving, setArchiving] = useState(false);
  const [archiveToast, setArchiveToast] = useState<string | null>(null);
  const [showHistoryModal, setShowHistoryModal] = useState(false);

  const { broadcastPageChange, broadcastDiffSelect } = useCrossWindowSync(taskId || null);
  const { user: authUser, logout } = useAuthStore();

  const handlePageChange = (side: 'old' | 'new', page: number) => {
    setCurrentPage(side, page);
    broadcastPageChange(side, page);
  };

  const handleDiffClick = (diff: any) => {
    setSelectedDiffId(diff.id);
    openDiffPopup(diff);
    broadcastDiffSelect(diff.id);
  };

  const handleListDiffClick = (diffId: string) => {
    setSelectedDiffId(diffId);
    broadcastDiffSelect(diffId);
    const diff = filteredItems?.find((d) => d.id === diffId);
    if (diff) {
      openDiffPopup(diff);
      if (diff.old_bbox && currentPage.old !== diff.old_bbox.page) {
        handlePageChange('old', diff.old_bbox.page);
      }
      if (diff.new_bbox && currentPage.new !== diff.new_bbox.page) {
        handlePageChange('new', diff.new_bbox.page);
      }
    }
  };

  const loadChecklist = useCallback(
    async (comparisonId: string) => {
      try {
        const checklistData = await checklistApi.getChecklist(comparisonId);
        setChecklist(checklistData);
      } catch {
        setChecklist([]);
      }
    },
    [setChecklist]
  );

  useEffect(() => {
    if (taskId) {
      setTaskId(taskId);
    }
  }, [taskId, setTaskId]);

  useEffect(() => {
    if (!taskId) {
      return undefined;
    }

    let retryCount = 0;
    let reconnectTimer: number | undefined;

    const connectWS = () => {
      const socket = new WebSocket(buildWebSocketUrl(`/ws/compare/${taskId}`));
      wsConnectionRef.current = socket;

      socket.onopen = () => {
        retryCount = 0;
      };

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as WsMessage;

          if (message.event === 'progress') {
            const progress = message.data ?? {};
            setStatus({
              task_id: taskId,
              status: progress.status ?? 'parsing',
              progress_percent: typeof progress.percent === 'number' ? progress.percent : 0,
              current_step: progress.step ?? '',
              error_message: progress.error_message ?? null,
            });
            return;
          }

          if (message.event === 'complete') {
            const payload =
              typeof message.data === 'string'
                ? (JSON.parse(message.data) as DiffReport)
                : message.data;

            if (payload) {
              setReport(payload);
              void loadChecklist(taskId);
            }
            return;
          }

          if (message.event === 'error') {
            setError(message.data?.message ?? 'WebSocket 連線失敗');
          }
        } catch {
          setError('即時更新資料格式異常');
        }
      };

      socket.onclose = () => {
        wsConnectionRef.current = null;
        if (retryCount < 5) {
          retryCount += 1;
          reconnectTimer = window.setTimeout(connectWS, 1000 * retryCount);
        }
      };
    };

    connectWS();

    return () => {
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
      }
      wsConnectionRef.current?.close();
      wsConnectionRef.current = null;
    };
  }, [loadChecklist, setReport, setStatus, taskId]);

  useEffect(() => {
    if (!taskId) {
      return undefined;
    }

    const loadComparison = async () => {
      try {
        setIsLoading(true);
        setError(null);

        const statusData = await compareApi.getStatus(taskId);
        setStatus(statusData);

        if (statusData.status === 'done') {
          const reportData = await compareApi.getResult(taskId);
          setReport(reportData);
          await loadChecklist(taskId);
        } else if (statusData.status === 'error') {
          setError(statusData.error_message || '比較任務失敗');
        }
      } catch (err: unknown) {
        const detail = isAxiosError<{ detail?: string }>(err) ? err.response?.data?.detail : undefined;
        setError(detail || '載入比較結果失敗');
      } finally {
        setIsLoading(false);
      }
    };

    void loadComparison();

    const interval = window.setInterval(async () => {
      if (wsConnectionRef.current?.readyState === WebSocket.OPEN) {
        return;
      }

      try {
        const statusData = await compareApi.getStatus(taskId);
        setStatus(statusData);

        if (statusData.status === 'done') {
          const reportData = await compareApi.getResult(taskId);
          setReport(reportData);
          await loadChecklist(taskId);
          window.clearInterval(interval);
        } else if (statusData.status === 'error') {
          setError(statusData.error_message || '比較任務失敗');
          window.clearInterval(interval);
        }
      } catch {
        // Ignore transient polling errors; the next poll or websocket retry will recover.
      }
    }, 2000);

    return () => window.clearInterval(interval);
  }, [loadChecklist, setReport, setStatus, taskId]);

  useEffect(() => {
    if (!showExportMenu) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!exportMenuRef.current?.contains(event.target as Node)) {
        setShowExportMenu(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [showExportMenu]);

  const handleConfirmDiff = async (diffId: string, reviewer?: string, note?: string) => {
    if (!taskId) {
      return;
    }

    try {
      await reviewApi.confirmDiff(taskId, {
        diff_item_id: diffId,
        action: 'confirmed',
        reviewer,
        note,
      });
      storeConfirmDiff(diffId, reviewer, note);
    } catch (err) {
      console.error('Failed to confirm diff:', err);
    }
  };

  const handleFlagDiff = async (diffId: string, reviewer?: string, note?: string) => {
    if (!taskId) {
      return;
    }

    try {
      await reviewApi.confirmDiff(taskId, {
        diff_item_id: diffId,
        action: 'flagged',
        reviewer,
        note,
      });
      storeFlagDiff(diffId, reviewer, note);
    } catch (err) {
      console.error('Failed to flag diff:', err);
    }
  };

  const handleChecklistUpdate = async (itemId: string, updates: Partial<ChecklistItem>) => {
    if (!taskId) {
      return;
    }

    try {
      await checklistApi.updateChecklistItem(taskId, itemId, updates);
      updateChecklistItem(itemId, updates);
    } catch (err) {
      console.error('Failed to update checklist item:', err);
    }
  };

  const handleExportDownload = (format: 'report' | 'excel' | 'pdf' | 'log' | 'log-csv' | 'log-txt') => {
    if (!taskId) {
      return;
    }

    window.open(buildApiUrl(`/api/export/${taskId}/${format}`), '_blank', 'noopener,noreferrer');
    setShowExportMenu(false);
  };

  const handleVerifyAndArchive = async () => {
    if (!taskId) return;
    setArchiving(true);
    try {
      const result = await archiveApi.verify(taskId, {
        reviewer: authUser?.display_name || authUser?.username,
      });
      const msg = result.is_new_archive
        ? '已存檔，建立新案例紀錄'
        : '已存檔，新增至既有案例紀錄';
      setArchiveToast(msg);
      setTimeout(() => setArchiveToast(null), 3500);
    } catch {
      setArchiveToast('存檔失敗，請稍後再試');
      setTimeout(() => setArchiveToast(null), 3500);
    } finally {
      setArchiving(false);
    }
  };

  const getPdfUrl = (version: 'old' | 'new') => {
    if (!taskId) {
      return null;
    }

    return buildApiUrl(`/api/compare/${taskId}/pdf/${version}`);
  };

  // Any non-terminal status (including snapshotting) is still in-progress
  const isProcessing = status !== null && status.status !== 'done' && status.status !== 'error';
  const isFetchingResult = status?.status === 'done' && !report;

  if (isLoading || isProcessing || isFetchingResult) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[linear-gradient(180deg,_#f5f5f5_0%,_#eef4ef_100%)]">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-6 border-4 border-primary-600 border-t-transparent rounded-full animate-spin" />
          <h2 className="text-xl font-medium text-gray-900 mb-2">
            {isFetchingResult ? '準備比較報告中' : '載入比較結果中'}
          </h2>
          <p className="text-gray-600">
            {status?.current_step ? `正在 ${status.current_step}...` : '請稍候...'}
          </p>
          {status?.progress_percent ? (
            <div className="mt-4 w-64 mx-auto">
              <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary-600 transition-all duration-300"
                  style={{ width: `${status.progress_percent}%` }}
                />
              </div>
              <p className="text-sm text-gray-600 mt-2">{status.progress_percent}% 完成</p>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[linear-gradient(180deg,_#f5f5f5_0%,_#eef4ef_100%)]">
        <div className="text-center p-8 max-w-md bg-white rounded-3xl border border-white shadow-large">
          <AlertCircle className="w-16 h-16 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-medium text-gray-900 mb-2">載入失敗</h2>
          <p className="text-gray-600 mb-6">{error}</p>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="px-6 py-3 bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors"
          >
            返回上傳頁面
          </button>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[linear-gradient(180deg,_#f5f5f5_0%,_#eef4ef_100%)]">
        <div className="w-16 h-16 border-4 border-primary-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const stats = getStats();

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,_#f5f5f5_0%,_#edf3ee_100%)] flex flex-col">
      <header className="relative z-10 border-b border-[#dfe7e2] bg-white/90 px-6 py-4 backdrop-blur">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.18em] text-primary-700">Review Workspace</div>
              <h1 className="text-xl font-bold text-gray-900">PDF 差異比對系統</h1>
            </div>
            <div className="text-sm text-gray-600 rounded-full border border-gray-200 bg-[#F5F5F5] px-3 py-1.5">
              任務 ID: <span className="font-mono text-gray-800">{taskId}</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center space-x-1 border border-gray-200 rounded-xl bg-white/50 px-2 py-1.5 backdrop-blur">
              <button
                type="button"
                onClick={() => setScale(Math.max(0.25, scale - 0.25))}
                className="p-1.5 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                title="縮小"
              >
                <ZoomOut size={16} />
              </button>
              <span className="text-sm font-medium w-12 text-center text-gray-700">{Math.round(scale * 100)}%</span>
              <button
                type="button"
                onClick={() => setScale(Math.min(3.0, scale + 0.25))}
                className="p-1.5 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                title="放大"
              >
                <ZoomIn size={16} />
              </button>
            </div>
            
            <button
              type="button"
              onClick={() => setGrayscaleEnabled(!grayscaleEnabled)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border transition-colors text-sm font-medium ${
                grayscaleEnabled
                  ? 'border-primary-200 bg-primary-50 text-primary-700'
                  : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
              }`}
              title="切換灰階模式"
            >
              灰階
            </button>

            <button
              type="button"
              onClick={() => setShowDiffLabels(!showDiffLabels)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border transition-colors text-sm font-medium ${
                showDiffLabels
                  ? 'border-primary-200 bg-primary-50 text-primary-700'
                  : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
              }`}
              title="顯示/隱藏差異標籤"
            >
              差異訊息
            </button>

            <button
              type="button"
              onClick={() => navigate('/')}
              className="flex items-center gap-2 px-4 py-2.5 bg-white text-gray-700 rounded-xl border border-gray-200 hover:bg-gray-100 transition-colors"
            >
              <Upload size={16} />
              <span>新比較</span>
            </button>

            {authUser?.role === 'admin' && (
              <button
                type="button"
                onClick={() => navigate('/admin')}
                className="flex items-center gap-2 px-3 py-2.5 bg-white text-gray-700 rounded-xl border border-gray-200 hover:bg-gray-100 transition-colors"
                title="帳號管理"
              >
                <Settings size={16} />
              </button>
            )}
            {authUser && status?.status === 'done' && (
              <>
                <button
                  type="button"
                  onClick={handleVerifyAndArchive}
                  disabled={archiving}
                  className="flex items-center gap-2 px-4 py-2.5 bg-white text-gray-700 rounded-xl border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-60"
                  title="完成驗證並存檔"
                >
                  <Save size={16} />
                  <span>{archiving ? '存檔中…' : '存檔'}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setShowHistoryModal(true)}
                  className="flex items-center gap-2 px-4 py-2.5 bg-white text-gray-700 rounded-xl border border-gray-200 hover:bg-gray-50 transition-colors"
                  title="查閱檢核歷史"
                >
                  <ClipboardList size={16} />
                  <span>檢核歷史</span>
                </button>
              </>
            )}

            <div className="relative" ref={exportMenuRef}>
              <button
                type="button"
                onClick={() => setShowExportMenu((current) => !current)}
                className="flex items-center gap-2 px-4 py-2.5 bg-primary-600 text-white rounded-xl hover:bg-primary-700 shadow-soft transition-colors"
              >
                <Download size={16} />
                <span>下載匯出</span>
                <ChevronDown size={16} />
              </button>

              {showExportMenu ? (
                <div className="absolute right-0 mt-2 w-56 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-large z-20">
                  <button
                    type="button"
                    onClick={() => handleExportDownload('report')}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <span>差異檢核報告</span>
                    <span className="text-xs text-gray-400">PDF</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExportDownload('excel')}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <span>差異檢核明細</span>
                    <span className="text-xs text-gray-400">Excel</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExportDownload('pdf')}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <span>標註差異 PDF</span>
                    <span className="text-xs text-gray-400">PDF</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExportDownload('log-csv')}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <span>審核 Log</span>
                    <span className="text-xs text-gray-400">CSV</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExportDownload('log')}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <span>完整 Log</span>
                    <span className="text-xs text-gray-400">JSON</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExportDownload('log-txt')}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <span>審核紀錄</span>
                    <span className="text-xs text-gray-400">TXT</span>
                  </button>
                </div>
              ) : null}
            </div>

            {/* User info */}
            {authUser && (
              <div className="flex items-center gap-2 pl-2 border-l border-gray-200">
                <span className="text-sm text-gray-600">{authUser.display_name}</span>
                <button
                  type="button"
                  onClick={() => { logout(); navigate('/login'); }}
                  className="p-2 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                  title="登出"
                >
                  <LogOut size={16} />
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <aside className="w-80 bg-white/88 border-r border-[#dfe7e2] flex flex-col backdrop-blur">
          <div className="p-4 border-b border-[#e7ece8]">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-medium text-gray-900">差異摘要</h2>
              <button
                type="button"
                onClick={toggleReviewedOnly}
                className={`p-2 rounded-xl border transition-colors ${
                  reviewedOnly
                    ? 'border-primary-200 bg-primary-50 text-primary-700'
                    : 'border-gray-200 bg-[#F5F5F5] text-gray-700 hover:bg-gray-100'
                }`}
                title={reviewedOnly ? '顯示所有差異' : '僅顯示未審核差異'}
              >
                {reviewedOnly ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="rounded-2xl border border-primary-100 bg-primary-50 p-3">
                <div className="text-sm text-primary-700">總差異</div>
                <div className="text-2xl font-bold text-primary-900">{stats.total}</div>
              </div>
              <div className="rounded-2xl border border-[#dcefe5] bg-[#eef7f1] p-3">
                <div className="text-sm text-primary-700">已審核</div>
                <div className="text-2xl font-bold text-primary-900">{stats.reviewed}</div>
              </div>
              <div className="rounded-2xl border border-gray-200 bg-[#F5F5F5] p-3">
                <div className="text-sm text-gray-600">待審核</div>
                <div className="text-2xl font-bold text-gray-900">{stats.pending}</div>
              </div>
              <div className="rounded-2xl border border-red-100 bg-red-50 p-3">
                <div className="text-sm text-red-700">異常</div>
                <div className="text-2xl font-bold text-red-900">0</div>
              </div>
            </div>

            <div className="space-y-2 rounded-2xl bg-[#F5F5F5] p-4">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-600">新增內容</span>
                <span className="font-medium text-gray-900">{stats.added}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-600">刪除內容</span>
                <span className="font-medium text-gray-900">{stats.deleted}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-600">數值修改</span>
                <span className="font-medium text-gray-900">{stats.modified}</span>
              </div>
            </div>
          </div>

          <div className="flex border-b border-[#e7ece8]">
            <button
              onClick={() => setLeftTab('diff_list')}
              className={`flex-1 py-3 text-sm font-medium transition-colors ${leftTab === 'diff_list' ? 'text-primary-700 border-b-2 border-primary-600 bg-white/50' : 'text-gray-500 hover:text-gray-800'}`}
            >
              差異清單
            </button>
            <button
              onClick={() => setLeftTab('checklist')}
              className={`flex-1 py-3 text-sm font-medium transition-colors ${leftTab === 'checklist' ? 'text-primary-700 border-b-2 border-primary-600 bg-white/50' : 'text-gray-500 hover:text-gray-800'}`}
            >
              外部核對表
            </button>
          </div>

          <div className="flex-1 flex flex-col overflow-hidden">
            {leftTab === 'diff_list' ? (
              <>
                <div className="p-3 border-b border-[#e7ece8]">
                  <SearchBar
                    diffItems={filteredItems}
                    searchQuery={searchQuery}
                    onSearchChange={setSearchQuery}
                    selectedDiffId={selectedDiffId}
                    onDiffSelect={setSelectedDiffId}
                  />
                </div>
                <div className="flex-1 overflow-hidden">
                  <DiffListPanel
                    diffItems={filteredItems}
                    selectedDiffId={selectedDiffId}
                    onDiffSelect={handleListDiffClick}
                  />
                </div>
              </>
            ) : (
              <div className="flex-1 p-4 overflow-auto">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium text-gray-900">核對清單</h3>
                  <button
                    type="button"
                    onClick={() => setShowChecklistUpload(true)}
                    className="text-sm px-3 py-1.5 bg-primary-50 text-primary-700 rounded-xl border border-primary-100 hover:bg-primary-100 transition-colors"
                  >
                    + 上傳
                  </button>
                </div>

                {checklist.length > 0 ? (
                  <ChecklistPanel
                    items={checklist}
                    comparisonId={taskId!}
                    onItemUpdate={handleChecklistUpdate}
                  />
                ) : (
                  <div className="text-center py-8 rounded-3xl bg-[#F5F5F5] border border-gray-200">
                    <div className="w-12 h-12 mx-auto mb-4 bg-white rounded-full flex items-center justify-center shadow-soft">
                      <BarChart3 className="text-primary-600" size={20} />
                    </div>
                    <p className="text-gray-700 mb-2">尚未上傳核對清單</p>
                    <p className="text-gray-500 text-sm mb-4">上傳 CSV 或 Excel 檔案以開始核對</p>
                    <button
                      type="button"
                      onClick={() => setShowChecklistUpload(true)}
                      className="px-4 py-2 bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors text-sm"
                    >
                      上傳核對清單
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </aside>

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="bg-white/75 border-b border-[#dfe7e2] px-6 backdrop-blur">
            <div className="flex space-x-1">
              <button
                type="button"
                onClick={() => setActiveTab('diffs')}
                className={`px-4 py-3 font-medium transition-colors ${
                  activeTab === 'diffs'
                    ? 'text-primary-700 border-b-2 border-primary-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                差異檢視
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('checklist')}
                className={`px-4 py-3 font-medium transition-colors ${
                  activeTab === 'checklist'
                    ? 'text-primary-700 border-b-2 border-primary-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                核對清單
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-hidden p-4">
            {activeTab === 'diffs' ? (
              <Suspense fallback={<InlineLoader label="Loading compare canvas" />}>
                <div className="h-full rounded-[28px] overflow-hidden border border-white shadow-large">
                  <SyncScrollContainer
                    leftContent={
                      <PDFViewer
                        file={getPdfUrl('old')}
                        currentPage={currentPage.old}
                        onPageChange={(page) => handlePageChange('old', page)}
                        scale={scale}
                        grayscale={grayscaleEnabled}
                        onGrayscaleChange={setGrayscaleEnabled}
                        showControls={false}
                        diffItems={filteredItems}
                        selectedDiffId={selectedDiffId}
                        onDiffClick={handleDiffClick}
                        showDiffLabels={showDiffLabels}
                      />
                    }
                    rightContent={
                      <PDFViewer
                        file={getPdfUrl('new')}
                        currentPage={currentPage.new}
                        onPageChange={(page) => handlePageChange('new', page)}
                        scale={scale}
                        grayscale={grayscaleEnabled}
                        onGrayscaleChange={setGrayscaleEnabled}
                        showControls={false}
                        diffItems={filteredItems}
                        selectedDiffId={selectedDiffId}
                        onDiffClick={handleDiffClick}
                        showDiffLabels={showDiffLabels}
                      />
                    }
                    syncEnabled={scrollSyncEnabled}
                    onSyncToggle={setScrollSyncEnabled}
                    leftHidden={leftPanelHidden}
                    onLeftHiddenToggle={toggleLeftPanel}
                    taskId={taskId}
                    className="h-full"
                  />
                </div>
              </Suspense>
            ) : (
              <div className="h-full overflow-auto rounded-[28px] border border-white bg-white/90 p-4 shadow-large">
                {showChecklistUpload ? (
                  <Suspense fallback={<InlineLoader label="Loading checklist tools" />}>
                    <ChecklistUpload
                      comparisonId={taskId!}
                      onUploadComplete={() => {
                        void loadChecklist(taskId!);
                        setShowChecklistUpload(false);
                      }}
                    />
                  </Suspense>
                ) : (
                  <ChecklistPanel
                    items={checklist}
                    comparisonId={taskId!}
                    onItemUpdate={handleChecklistUpdate}
                  />
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <Suspense fallback={null}>
        <DiffPopup
          diff={selectedDiffForPopup}
          isOpen={diffPopupOpen}
          onClose={closeDiffPopup}
          onConfirm={handleConfirmDiff}
          onFlag={handleFlagDiff}
          taskId={taskId}
        />
      </Suspense>

      <footer className="bg-white/90 border-t border-[#dfe7e2] px-6 py-3 backdrop-blur">
        <div className="flex items-center justify-between text-sm text-gray-600">
          <div className="flex items-center space-x-4">
            <span>{report?.old_filename} ↔ {report?.new_filename}</span>
            <span>•</span>
            <span>建立時間: {report ? new Date(report.created_at).toLocaleString() : ''}</span>
          </div>
          <div className="flex items-center space-x-4">
            <span>同步滾動: {scrollSyncEnabled ? '啟用' : '停用'}</span>
            <span>•</span>
            <span>左側面板: {leftPanelHidden ? '隱藏' : '顯示'}</span>
          </div>
        </div>
      </footer>

      {taskId && (
        <VerificationHistoryModal
          comparisonId={taskId}
          isOpen={showHistoryModal}
          onClose={() => setShowHistoryModal(false)}
        />
      )}

      {archiveToast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-5 py-3 bg-gray-900 text-white text-sm rounded-xl shadow-lg">
          {archiveToast}
        </div>
      )}
    </div>
  );
};

export default ComparePage;
