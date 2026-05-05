import React, { useEffect, useState } from 'react';
import { Download, FileText, X } from 'lucide-react';
import { ArchiveRecord, VerificationSession, archiveApi } from '../services/api';

interface Props {
  comparisonId: string;
  isOpen: boolean;
  onClose: () => void;
}

export default function VerificationHistoryModal({ comparisonId, isOpen, onClose }: Props) {
  const [archive, setArchive] = useState<ArchiveRecord | null>(null);
  const [sessions, setSessions] = useState<VerificationSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    setError(null);
    archiveApi.getHistory(comparisonId)
      .then(({ archive, sessions }) => {
        setArchive(archive);
        setSessions(sessions);
      })
      .catch(() => setError('無法載入檢核歷史'))
      .finally(() => setLoading(false));
  }, [isOpen, comparisonId]);

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
      <div className="relative w-full max-w-3xl mx-4 bg-white rounded-2xl shadow-2xl flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-bold text-gray-900">檢核歷史紀錄</h2>
            {archive && (
              <p className="text-xs text-gray-500 mt-0.5">
                {archive.old_filename} ↔ {archive.new_filename}
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
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 border-b border-gray-100">
                  <th className="pb-2 pr-4 font-medium">驗證時間</th>
                  <th className="pb-2 pr-4 font-medium">審核者</th>
                  <th className="pb-2 pr-4 font-medium text-center">總差異</th>
                  <th className="pb-2 pr-4 font-medium text-center">已確認</th>
                  <th className="pb-2 pr-4 font-medium text-center">標記</th>
                  <th className="pb-2 font-medium">備注</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s, i) => (
                  <tr key={s.id} className={`border-b border-gray-50 ${i % 2 === 0 ? '' : 'bg-gray-50/50'}`}>
                    <td className="py-3 pr-4 text-gray-700 whitespace-nowrap">{fmt(s.verified_at)}</td>
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
