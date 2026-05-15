import React, { useEffect, useMemo, useState } from 'react';
import { Download, FileText, Search, X } from 'lucide-react';
import { ArchiveRecord, ReviewLogChange, VerificationSession, archiveApi } from '../services/api';

interface Props {
  comparisonId: string;
  isOpen: boolean;
  onClose: () => void;
}

export default function VerificationHistoryModal({ comparisonId, isOpen, onClose }: Props) {
  const [archive, setArchive] = useState<ArchiveRecord | null>(null);
  const [sessions, setSessions] = useState<VerificationSession[]>([]);
  const [reviewLogs, setReviewLogs] = useState<ReviewLogChange[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    const resetTimer = window.setTimeout(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
    }, 0);
    archiveApi.getHistory(comparisonId)
      .then(({ archive, sessions, review_logs }) => {
        if (cancelled) return;
        setArchive(archive);
        setSessions(sessions);
        setReviewLogs(review_logs || []);
      })
      .catch(() => {
        if (cancelled) return;
        setError('無法載入檢核歷史');
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
      window.clearTimeout(resetTimer);
    };
  }, [isOpen, comparisonId]);

  const q = searchQuery.trim().toLowerCase();
  const filteredSessions = useMemo(() => {
    if (!q) return sessions;
    return sessions.filter((s) =>
      (s.case_number || '').toLowerCase().includes(q) ||
      (archive?.case_number || '').toLowerCase().includes(q) ||
      (s.reviewer || '').toLowerCase().includes(q) ||
      (s.notes || '').toLowerCase().includes(q) ||
      s.comparison_id.toLowerCase().includes(q)
    );
  }, [archive?.case_number, q, sessions]);

  const modifiedReviewLogs = useMemo(() => {
    const logs = reviewLogs.filter((log) => log.change_type === 'modified');
    if (!q) return logs;
    return logs.filter((log) =>
      log.diff_item_id.toLowerCase().includes(q) ||
      log.action.toLowerCase().includes(q) ||
      (log.reviewer || '').toLowerCase().includes(q) ||
      (log.note || '').toLowerCase().includes(q) ||
      (log.change_summary || '').toLowerCase().includes(q)
    );
  }, [q, reviewLogs]);

  if (!isOpen) return null;

  const fmt = (iso: string) => {
    try {
      return new Date(iso).toLocaleString('zh-TW', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative w-full max-w-5xl mx-4 bg-white rounded-2xl shadow-2xl flex flex-col max-h-[84vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-bold text-gray-900">檢核歷史紀錄</h2>
            {archive && (
              <p className="text-xs text-gray-500 mt-0.5">
                {archive.case_number ? `${archive.case_number} · ` : ''}{archive.old_filename} ↔ {archive.new_filename}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Archive files */}
        {archive && (
          <div className="px-6 py-3 border-b border-gray-100 bg-gray-50 flex flex-wrap gap-2">
            <span className="text-xs text-gray-500 self-center mr-1">存檔下載：</span>
            <a
              href={archiveApi.getFileUrl(archive.id, 'old_pdf')}
              download
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg text-gray-700 hover:bg-gray-100 transition-colors"
            >
              <Download size={12} />
              舊版 PDF
            </a>
            <a
              href={archiveApi.getFileUrl(archive.id, 'new_pdf')}
              download
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg text-gray-700 hover:bg-gray-100 transition-colors"
            >
              <Download size={12} />
              新版 PDF
            </a>
            {archive.annotated_archive_path && (
              <a
                href={archiveApi.getFileUrl(archive.id, 'annotated_pdf')}
                download
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary-50 border border-primary-200 rounded-lg text-primary-700 hover:bg-primary-100 transition-colors"
              >
                <Download size={12} />
                標注差異 PDF
              </a>
            )}
          </div>
        )}

        <div className="px-6 py-3 border-b border-gray-100">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="搜尋案號、審核人員、備註、修改內容..."
              className="w-full pl-9 pr-4 py-2.5 border border-gray-200 rounded-xl bg-gray-50/80 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:bg-white transition-all text-sm"
            />
          </div>
        </div>

        {/* Sessions */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading && (
            <div className="flex justify-center py-8">
              <div className="w-8 h-8 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {error && (
            <p className="text-center text-red-500 py-6">{error}</p>
          )}

          {!loading && !error && sessions.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400">
              <FileText size={40} className="mb-3 opacity-40" />
              <p className="text-sm">尚無檢核紀錄</p>
            </div>
          )}

          {!loading && sessions.length > 0 && (
            <div className="space-y-6">
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-900">留存紀錄</h3>
                  <span className="text-xs text-gray-400">
                    {filteredSessions.length}{searchQuery ? ` / ${sessions.length}` : ''} 筆
                  </span>
                </div>
                {filteredSessions.length === 0 ? (
                  <p className="py-6 text-center text-sm text-gray-400">沒有符合搜尋條件的留存紀錄</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-gray-500 border-b border-gray-100">
                        <th className="pb-2 pr-4 font-medium">驗證時間</th>
                        <th className="pb-2 pr-4 font-medium">案號</th>
                        <th className="pb-2 pr-4 font-medium">審核人員</th>
                        <th className="pb-2 pr-4 font-medium text-center">總差異</th>
                        <th className="pb-2 pr-4 font-medium text-center">已確認</th>
                        <th className="pb-2 pr-4 font-medium text-center">標記</th>
                        <th className="pb-2 font-medium">備註</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSessions.map((s, i) => (
                        <tr key={s.id} className={`border-b border-gray-50 ${i % 2 === 0 ? '' : 'bg-gray-50/50'}`}>
                          <td className="py-3 pr-4 text-gray-700 whitespace-nowrap">{fmt(s.verified_at)}</td>
                          <td className="py-3 pr-4 text-gray-700">{s.case_number || archive?.case_number || '—'}</td>
                          <td className="py-3 pr-4 text-gray-700">{s.reviewer || '—'}</td>
                          <td className="py-3 pr-4 text-center text-gray-700">{s.total_diffs ?? '—'}</td>
                          <td className="py-3 pr-4 text-center">
                            <span className="px-2 py-0.5 rounded-full text-xs bg-green-50 text-green-700">
                              {s.confirmed ?? 0}
                            </span>
                          </td>
                          <td className="py-3 pr-4 text-center">
                            <span className="px-2 py-0.5 rounded-full text-xs bg-red-50 text-red-700">
                              {s.flagged ?? 0}
                            </span>
                          </td>
                          <td className="py-3 text-gray-500 text-xs">{s.notes || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-900">審核修改內容</h3>
                  <span className="text-xs text-gray-400">{modifiedReviewLogs.length} 筆</span>
                </div>
                {modifiedReviewLogs.length === 0 ? (
                  <p className="rounded-xl border border-dashed border-gray-200 bg-gray-50/70 py-5 text-center text-sm text-gray-400">
                    {searchQuery ? '沒有符合搜尋條件的修改內容' : '尚無審核修改紀錄'}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {modifiedReviewLogs.map((log) => (
                      <div key={log.id} className="rounded-xl border border-gray-100 bg-gray-50/70 px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                          <span>{fmt(log.created_at)}</span>
                          <span className="rounded-full bg-white px-2 py-0.5 border border-gray-200">差異 {log.diff_item_id}</span>
                          <span>{log.reviewer || '未指定審核人員'}</span>
                        </div>
                        <p className="mt-1.5 text-sm text-gray-800">{log.change_summary}</p>
                        {log.note && (
                          <p className="mt-1 text-xs text-gray-500">備註：{log.note}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-3 border-t border-gray-100 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-xl hover:bg-gray-200 transition-colors"
          >
            關閉
          </button>
        </div>
      </div>
    </div>
  );
}
