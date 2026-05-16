import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { isAxiosError } from 'axios';
import { useNavigate } from 'react-router-dom';
import { Upload, File, Folder, AlertCircle, CheckCircle, XCircle, Clock, ChevronRight, Search, Download, LogOut, Settings, User, Trash2, Hash } from 'lucide-react';
import { compareApi, projectApi, buildAuthedUrl } from '../services/api';
import { ComparisonInfo } from '../services/types';
import { useAuthStore } from '../stores/authStore';

function getSuggestedProjectName(oldName: string, newName: string): string {
  const stripExt = (n: string) => n.replace(/\.pdf$/i, '');
  const a = stripExt(oldName);
  const b = stripExt(newName);
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  const common = a.substring(0, i).replace(/[-_\s()（）]+$/, '').trim();
  const today = new Date();
  const dateStr = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}${String(today.getDate()).padStart(2, '0')}`;
  const timeStr = `${String(today.getHours()).padStart(2, '0')}${String(today.getMinutes()).padStart(2, '0')}${String(today.getSeconds()).padStart(2, '0')}`;
  return common ? `${common}_核對_${dateStr}_${timeStr}` : `PDF核對_${dateStr}_${timeStr}`;
}

const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const { user: authUser, logout } = useAuthStore();
  const [oldFile, setOldFile] = useState<File | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);
  const [caseNumber, setCaseNumber] = useState('');
  const [projectId, setProjectId] = useState('');
  const [projectIdUserEdited, setProjectIdUserEdited] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [recentComparisons, setRecentComparisons] = useState<ComparisonInfo[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historySearch, setHistorySearch] = useState('');
  const [openExportId, setOpenExportId] = useState<string | null>(null);
  const exportDropdownRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const navTimerRef = useRef<number | null>(null);

  const filteredHistory = useMemo(() => {
    if (!historySearch) return recentComparisons;
    const q = historySearch.toLowerCase();
    return recentComparisons.filter((comp) =>
      comp.old_filename.toLowerCase().includes(q) ||
      comp.new_filename.toLowerCase().includes(q) ||
      comp.project_id.toLowerCase().includes(q) ||
      (comp.case_number || '').toLowerCase().includes(q) ||
      (comp.latest_reviewer || '').toLowerCase().includes(q)
    );
  }, [recentComparisons, historySearch]);

  const handleHistoryExport = (compId: string, format: string) => {
    window.open(buildAuthedUrl(`/api/export/${compId}/${format}`), '_blank', 'noopener,noreferrer');
    setOpenExportId(null);
  };

  const handleDeleteConfirm = async (compId: string) => {
    if (deletingId) return;
    setConfirmDeleteId(null);
    setDeletingId(compId);
    try {
      await projectApi.deleteComparison(compId);
      setRecentComparisons((prev) => prev.filter((c) => c.id !== compId));
    } catch (err) {
      console.error('Failed to delete comparison:', err);
    } finally {
      setDeletingId(null);
    }
  };

  const handleExportAll = () => {
    window.open(projectApi.exportAllComparisonsUrl(), '_blank', 'noopener,noreferrer');
  };

  useEffect(() => {
    const fetchHistory = async () => {
      setIsLoadingHistory(true);
      try {
        const history = await projectApi.listAllComparisons(50);
        setRecentComparisons(history);
      } catch (err) {
        console.error('Failed to fetch history:', err);
      } finally {
        setIsLoadingHistory(false);
      }
    };
    fetchHistory();
  }, []);

  // Close export dropdown on outside click
  useEffect(() => {
    if (!openExportId) return;
    const handleClickOutside = (event: MouseEvent) => {
      const el = exportDropdownRefs.current[openExportId];
      if (el && !el.contains(event.target as Node)) {
        setOpenExportId(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [openExportId]);

  // Cancel the post-upload navigate timer if user leaves the page mid-countdown
  useEffect(() => {
    return () => {
      if (navTimerRef.current !== null) {
        window.clearTimeout(navTimerRef.current);
        navTimerRef.current = null;
      }
    };
  }, []);

  // Auto-suggest project name when both files are selected (only if user hasn't edited)
  useEffect(() => {
    if (oldFile && newFile && !projectIdUserEdited) {
      setProjectId(getSuggestedProjectName(oldFile.name, newFile.name));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oldFile, newFile]);

  const validateFile = (file: File): boolean => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('僅支援 PDF 檔案格式');
      return false;
    }
    if (file.size > 50 * 1024 * 1024) { // 50MB
      setError('檔案大小超過 50MB 限制');
      return false;
    }
    return true;
  };

  const handleFileSelect = (side: 'old' | 'new', files: FileList | null) => {
    if (!files || files.length === 0) return;
    
    const file = files[0];
    if (!validateFile(file)) return;
    
    setError(null);
    if (side === 'old') {
      setOldFile(file);
    } else {
      setNewFile(file);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent, side: 'old' | 'new') => {
    e.preventDefault();
    setIsDragging(false);
    
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      const file = files[0];
      if (validateFile(file)) {
        setError(null);
        if (side === 'old') {
          setOldFile(file);
        } else {
          setNewFile(file);
        }
      }
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!oldFile || !newFile) {
      setError('請選擇舊版與新版 PDF 檔案');
      return;
    }

    setIsUploading(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await compareApi.uploadFiles(
        oldFile,
        newFile,
        projectId || undefined,
        caseNumber.trim() || undefined
      );
      setSuccess('檔案上傳成功！正在進行比對分析...');
      
      // Redirect to compare page after a short delay (cancellable on unmount)
      navTimerRef.current = window.setTimeout(() => {
        navTimerRef.current = null;
        navigate(`/compare/${result.task_id}`);
      }, 1500);
    } catch (err: unknown) {
      const detail = isAxiosError<{ detail?: string }>(err) ? err.response?.data?.detail : undefined;
      setError(detail || '上傳失敗，請稍後再試');
    } finally {
      setIsUploading(false);
    }
  };

  const FileUploadArea = ({ side, label, file }: { side: 'old' | 'new'; label: string; file: File | null }) => (
    <div
      onDrop={(e) => handleDrop(e, side)}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-all ${
        isDragging ? 'border-primary-500 bg-primary-50' : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
      }`}
    >
      <input
        type="file"
        id={`${side}-upload`}
        className="hidden"
        accept=".pdf"
        onChange={(e) => handleFileSelect(side, e.target.files)}
        disabled={isUploading}
      />
      
      {file ? (
        <div className="space-y-4">
          <div className="flex items-center justify-center">
            <div className="p-3 bg-green-100 rounded-full">
              <CheckCircle className="text-green-600" size={32} />
            </div>
          </div>
          <div>
            <h3 className="font-medium text-gray-900 mb-1">{label} 已選擇</h3>
            <div className="flex items-center justify-center space-x-2 text-gray-600">
              <File size={16} />
              <span className="text-sm truncate max-w-xs">{file.name}</span>
            </div>
            <p className="text-sm text-gray-500 mt-1">
              {(file.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
          <button
            type="button"
            onClick={() => side === 'old' ? setOldFile(null) : setNewFile(null)}
            className="px-4 py-2 text-sm bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors"
            disabled={isUploading}
          >
            移除檔案
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-center">
            <div className="p-3 bg-gray-100 rounded-full">
              <Upload className="text-gray-400" size={32} />
            </div>
          </div>
          <div>
            <h3 className="font-medium text-gray-900 mb-1">{label}</h3>
            <p className="text-gray-600">拖放 PDF 檔案到此處，或點擊選擇檔案</p>
          </div>
          <label
            htmlFor={`${side}-upload`}
            className={`inline-block px-6 py-3 rounded-lg font-medium transition-colors cursor-pointer ${
              isUploading
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-primary-600 text-white hover:bg-primary-700'
            }`}
          >
            選擇檔案
          </label>
        </div>
      )}
    </div>
  );

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(0,153,68,0.10),_transparent_38%),linear-gradient(180deg,_#f5f5f5_0%,_#eef4ef_100%)] flex items-center justify-center p-4">
      <div className="w-full max-w-4xl">
        {/* Header */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center rounded-full border border-primary-200 bg-white/80 px-4 py-1.5 text-sm font-medium text-primary-700 shadow-soft backdrop-blur">
            Smart PDF Review
          </div>
          <h1 className="mt-4 text-4xl font-bold tracking-tight text-gray-900 mb-3">PDF 差異比對系統</h1>
          <p className="text-gray-600 max-w-2xl mx-auto leading-7">
            上傳新舊版保險 DM 檔案，系統將自動比對文字與數字差異，並在灰階化的 PDF 上以彩色標記呈現。
          </p>
          {/* User controls */}
          {authUser && (
            <div className="mt-4 inline-flex items-center gap-3">
              <span className="text-sm text-gray-600 bg-white/80 rounded-full px-3 py-1.5 border border-gray-200">
                <User size={14} className="inline -mt-0.5 mr-1" />{authUser.display_name}
              </span>
              {authUser.role === 'admin' && (
                <button
                  onClick={() => navigate('/admin')}
                  className="text-sm text-gray-600 bg-white/80 rounded-full px-3 py-1.5 border border-gray-200 hover:bg-gray-50 transition-colors"
                >
                  <Settings size={14} className="inline -mt-0.5 mr-1" />帳號管理
                </button>
              )}
              <button
                onClick={() => { logout(); navigate('/login'); }}
                className="text-sm text-gray-500 bg-white/80 rounded-full px-3 py-1.5 border border-gray-200 hover:bg-red-50 hover:text-red-600 transition-colors"
              >
                <LogOut size={14} className="inline -mt-0.5 mr-1" />登出
              </button>
            </div>
          )}
        </div>

        {/* Upload form */}
        <div className="bg-white/95 rounded-[28px] shadow-large border border-white p-8 backdrop-blur">
          <form onSubmit={handleSubmit}>
            {/* Case number + project selection */}
            <div className="mb-5 rounded-2xl border border-gray-100 bg-gray-50/70 px-3 py-3">
              <div className="grid grid-cols-1 lg:grid-cols-[0.85fr_1.35fr] gap-3">
                <label className="flex items-center gap-2">
                  <span className="shrink-0 inline-flex items-center gap-1.5 text-xs font-medium text-gray-800">
                    <Hash className="text-gray-400" size={14} />
                    案號 <span className="font-normal text-gray-400">選填</span>
                  </span>
                  <input
                    type="text"
                    value={caseNumber}
                    onChange={(e) => setCaseNumber(e.target.value)}
                    placeholder="留存檔名前綴"
                    className="min-w-0 flex-1 px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    disabled={isUploading}
                  />
                </label>

                <label className="flex items-center gap-2">
                  <span className="shrink-0 inline-flex items-center gap-1.5 text-xs font-medium text-gray-800">
                    <Folder className="text-gray-400" size={14} />
                    專案設定 <span className="font-normal text-gray-400">選填</span>
                  </span>
                  <input
                    type="text"
                    value={projectId}
                    onChange={(e) => { setProjectId(e.target.value); setProjectIdUserEdited(true); }}
                    placeholder="上傳兩個檔案後自動帶入共通名稱+核對日期時間"
                    className="min-w-0 flex-1 px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    disabled={isUploading}
                  />
                </label>
              </div>
              <p className="text-xs text-gray-500 mt-2 leading-relaxed">
                案號會作為留存/下載檔名前綴；專案設定仍會依檔名自動建議，也可手動修改。
              </p>
              {/* Reviewer info */}
              {authUser && (
                <div className="mt-2 flex items-center gap-2 text-xs">
                  <User size={14} className="text-gray-400" />
                  <span className="text-gray-500">審核人員：</span>
                  <span className="font-medium text-gray-800 bg-primary-50 px-2 py-0.5 rounded">{authUser.display_name}</span>
                  <span className="text-gray-400">(@{authUser.username})</span>
                </div>
              )}
            </div>

            {/* File upload areas */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
              <FileUploadArea
                side="old"
                label="舊版 PDF"
                file={oldFile}
              />
              <FileUploadArea
                side="new"
                label="新版 PDF"
                file={newFile}
              />
            </div>

            {/* Status messages */}
            {error && (
              <div className="mb-6 bg-red-50 border border-red-200 rounded-xl p-6 animate-fade-in">
                <div className="flex items-start space-x-4">
                  <AlertCircle className="text-red-500 mt-1" size={24} />
                  <div className="flex-1">
                    <h4 className="text-lg font-medium text-red-800 mb-2">上傳失敗</h4>
                    <p className="text-red-700">{error}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setError(null)}
                    className="p-2 rounded-full hover:bg-red-100 transition-colors"
                  >
                    <XCircle className="text-red-500" size={20} />
                  </button>
                </div>
              </div>
            )}

            {success && (
              <div className="mb-6 bg-green-50 border border-green-200 rounded-xl p-6 animate-fade-in">
                <div className="flex items-start space-x-4">
                  <CheckCircle className="text-green-500 mt-1" size={24} />
                  <div className="flex-1">
                    <h4 className="text-lg font-medium text-green-800 mb-2">上傳成功</h4>
                    <p className="text-green-700">{success}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Submit button */}
            <div className="flex items-center justify-between gap-6">
              <div className="text-sm text-gray-600">
                <p>支援 PDF 檔案格式，單一檔案最大 50MB</p>
                <p>比對過程可能需要數分鐘，視檔案大小而定</p>
              </div>
              <button
                type="submit"
                disabled={!oldFile || !newFile || isUploading}
                className={`px-8 py-4 rounded-lg font-medium text-lg transition-all ${
                  !oldFile || !newFile || isUploading
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-primary-600 text-white hover:bg-primary-700 shadow-lg hover:shadow-xl'
                }`}
              >
                {isUploading ? (
                  <div className="flex items-center space-x-3">
                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    <span>上傳與比對中...</span>
                  </div>
                ) : (
                  '開始比對'
                )}
              </button>
            </div>
          </form>
        </div>

        {/* History Section */}
        <div className="mt-8 bg-white/95 rounded-[28px] shadow-large border border-white p-8 backdrop-blur">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <Clock className="text-gray-400" size={24} />
              <h2 className="text-xl font-bold text-gray-900">最近比對紀錄</h2>
              <span className="text-sm text-gray-400">
                ({filteredHistory.length}{historySearch ? ` / ${recentComparisons.length}` : ''})
              </span>
            </div>
            <button
              type="button"
              onClick={handleExportAll}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-600 hover:text-primary-600 hover:border-primary-200 transition-colors"
              title="匯出全部比對紀錄 CSV"
            >
              <Download size={15} />
              匯出紀錄
            </button>
          </div>

          {/* Search box */}
          <div className="relative mb-4">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <input
              type="text"
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
              placeholder="搜尋檔案名稱、案號、審核人員..."
              className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl bg-gray-50/80 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:bg-white transition-all text-sm"
            />
          </div>

          {isLoadingHistory ? (
            <div className="text-center py-8">
              <div className="w-8 h-8 mx-auto mb-3 border-3 border-primary-600 border-t-transparent rounded-full animate-spin" />
              <p className="text-sm text-gray-500">載入中...</p>
            </div>
          ) : filteredHistory.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              {historySearch ? '找不到符合條件的紀錄' : '尚無比對紀錄'}
            </div>
          ) : (
            <div className="space-y-2 max-h-[480px] overflow-y-auto pr-1">
              {filteredHistory.map((comp) => (
                <div
                  key={comp.id}
                  className="group flex items-center p-3 bg-gray-50 hover:bg-primary-50 rounded-xl border border-gray-100 hover:border-primary-100 transition-all hover:shadow-sm"
                >
                  {/* Date */}
                  <div className="flex-shrink-0 w-28 mr-3">
                    <span className="text-xs font-medium text-gray-500 bg-white px-2 py-1 rounded-md shadow-sm border border-gray-100 block text-center">
                      {new Date(comp.created_at).toLocaleDateString('zh-TW', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>

                  {/* File names */}
                  <div className="flex-1 min-w-0 mr-3">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      {comp.case_number && (
                        <span className="inline-flex items-center gap-1 rounded-md bg-primary-50 px-2 py-0.5 text-xs font-medium text-primary-700 border border-primary-100">
                          <Hash size={11} />
                          {comp.case_number}
                        </span>
                      )}
                      {comp.latest_reviewer && (
                        <span className="inline-flex items-center gap-1 rounded-md bg-white px-2 py-0.5 text-xs text-gray-600 border border-gray-200">
                          <User size={11} />
                          {comp.latest_reviewer}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center space-x-2 text-sm">
                      <span className="text-gray-400 flex-shrink-0">舊:</span>
                      <span className="text-gray-700 truncate font-medium">{comp.old_filename}</span>
                    </div>
                    <div className="flex items-center space-x-2 text-sm mt-0.5">
                      <span className="text-gray-400 flex-shrink-0">新:</span>
                      <span className="text-gray-700 truncate font-medium">{comp.new_filename}</span>
                    </div>
                  </div>

                  {/* Status */}
                  <div className="flex-shrink-0 w-16 text-center mr-2">
                    {comp.status === 'done' ? (
                      <span className="text-xs text-green-600 font-medium bg-green-50 px-2 py-1 rounded-full">已完成</span>
                    ) : comp.status === 'error' ? (
                      <span className="text-xs text-red-600 font-medium bg-red-50 px-2 py-1 rounded-full">錯誤</span>
                    ) : (
                      <span className="text-xs text-blue-600 font-medium animate-pulse bg-blue-50 px-2 py-1 rounded-full">處理中</span>
                    )}
                  </div>

                  {/* Export button */}
                  {comp.status === 'done' && (
                    <div className="relative flex-shrink-0 mr-2" ref={(el) => { exportDropdownRefs.current[comp.id] = el; }}>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setOpenExportId(openExportId === comp.id ? null : comp.id); }}
                        className="p-2 rounded-lg border border-gray-200 bg-white text-gray-500 hover:text-primary-600 hover:border-primary-200 transition-colors"
                        title="匯出紀錄"
                      >
                        <Download size={16} />
                      </button>
                      {openExportId === comp.id && (
                        <div className="absolute right-0 top-full mt-1 w-44 bg-white rounded-xl border border-gray-200 shadow-lg z-20 overflow-hidden">
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleHistoryExport(comp.id, 'log-txt'); }}
                            className="flex w-full items-center justify-between px-3 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                          >
                            <span>審核紀錄</span>
                            <span className="text-xs text-gray-400">TXT</span>
                          </button>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleHistoryExport(comp.id, 'report'); }}
                            className="flex w-full items-center justify-between px-3 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                          >
                            <span>檢核報告</span>
                            <span className="text-xs text-gray-400">PDF</span>
                          </button>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleHistoryExport(comp.id, 'excel'); }}
                            className="flex w-full items-center justify-between px-3 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                          >
                            <span>差異明細</span>
                            <span className="text-xs text-gray-400">Excel</span>
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Delete button */}
                  {confirmDeleteId === comp.id ? (
                    <div className="flex-shrink-0 flex items-center gap-1 mr-1">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); handleDeleteConfirm(comp.id); }}
                        disabled={deletingId === comp.id}
                        className="px-2 py-1 text-xs bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                      >
                        {deletingId === comp.id ? '刪除中…' : '確認刪除'}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(null); }}
                        disabled={deletingId === comp.id}
                        className="px-2 py-1 text-xs bg-gray-200 text-gray-600 rounded-lg hover:bg-gray-300 transition-colors disabled:opacity-60"
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(comp.id); }}
                      disabled={deletingId === comp.id}
                      className="flex-shrink-0 w-8 h-8 rounded-full bg-white flex items-center justify-center text-gray-300 hover:text-red-500 hover:bg-red-50 transition-all shadow-sm mr-1 opacity-0 group-hover:opacity-100"
                      title="刪除此筆紀錄"
                    >
                      {deletingId === comp.id
                        ? <div className="w-3.5 h-3.5 border-2 border-red-400 border-t-transparent rounded-full animate-spin" />
                        : <Trash2 size={15} />}
                    </button>
                  )}

                  {/* Navigate arrow */}
                  <button
                    type="button"
                    onClick={() => navigate(`/compare/${comp.id}`)}
                    className="flex-shrink-0 w-8 h-8 rounded-full bg-white flex items-center justify-center text-gray-400 group-hover:text-primary-600 group-hover:translate-x-1 transition-all shadow-sm"
                  >
                    <ChevronRight size={18} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Features grid */}
        <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-white/90 p-6 rounded-2xl border border-white shadow-soft">
            <div className="w-12 h-12 bg-primary-50 rounded-2xl flex items-center justify-center mb-4">
              <span className="text-primary-700 font-bold">1</span>
            </div>
            <h3 className="font-medium text-gray-900 mb-2">雙欄同步視圖</h3>
            <p className="text-gray-600 text-sm">
              左右並排顯示新舊檔案，滾動自動同步，可隱藏左側面板專注新版內容。
            </p>
          </div>
          <div className="bg-white/90 p-6 rounded-2xl border border-white shadow-soft">
            <div className="w-12 h-12 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
              <span className="text-primary-700 font-bold">2</span>
            </div>
            <h3 className="font-medium text-gray-900 mb-2">空間映射標記</h3>
            <p className="text-gray-600 text-sm">
              灰階 PDF 上疊加彩色差異標記（橘色數值、綠色新增），保持閱讀語境。
            </p>
          </div>
          <div className="bg-white/90 p-6 rounded-2xl border border-white shadow-soft">
            <div className="w-12 h-12 bg-primary-100 rounded-2xl flex items-center justify-center mb-4">
              <span className="text-primary-700 font-bold">3</span>
            </div>
            <h3 className="font-medium text-gray-900 mb-2">智慧核對清單</h3>
            <p className="text-gray-600 text-sm">
              上傳 CSV/Excel 核對清單，系統自動匹配差異項目，加速審核流程。
            </p>
          </div>
        </div>

        {/* Footer note */}
        <div className="mt-8 text-center text-gray-500 text-sm">
          <p>系統使用 AI 文件解析技術，自動比對文字與數字差異，專為保險 DM 審核設計。</p>
          <p className="mt-1">資料僅儲存於本地，確保敏感資訊安全。</p>
        </div>
      </div>
    </div>
  );
};

export default UploadPage;
