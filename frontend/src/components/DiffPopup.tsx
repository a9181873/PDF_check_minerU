import React, { useEffect, useState } from 'react';
import { CheckCircle, Copy, ExternalLink, Eye, EyeOff, Flag, Maximize2, Minus, Plus, RotateCcw, X } from 'lucide-react';
import { TransformComponent, TransformWrapper } from 'react-zoom-pan-pinch';

import { buildAuthedUrl } from '../services/api';
import { DiffItem, DiffType } from '../services/types';
import { useAuthStore } from '../stores/authStore';

interface DiffPopupProps {
  diff: DiffItem | null;
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (diffId: string, reviewer?: string, note?: string) => void;
  onFlag: (diffId: string, reviewer?: string, note?: string) => void;
  taskId?: string | null;
  className?: string;
}

interface DiffPopupInnerProps extends DiffPopupProps {
  diff: DiffItem;
}

const getDiffLabel = (type: DiffType) => {
  switch (type) {
    case DiffType.ADDED:
      return '新增內容';
    case DiffType.DELETED:
      return '刪除內容';
    case DiffType.NUMBER_MODIFIED:
      return '數值修改';
    case DiffType.TEXT_MODIFIED:
      return '文字修改';
    default:
      return '內容修改';
  }
};

const getDiffColor = (type: DiffType) => {
  switch (type) {
    case DiffType.ADDED:
      return 'text-diff-added bg-diff-added/10 border-diff-added';
    case DiffType.DELETED:
      return 'text-diff-deleted bg-diff-deleted/10 border-diff-deleted';
    case DiffType.NUMBER_MODIFIED:
      return 'text-diff-modified bg-diff-modified/10 border-diff-modified';
    case DiffType.TEXT_MODIFIED:
      return 'text-diff-text bg-diff-text/10 border-diff-text';
    default:
      return 'text-gray-600 bg-gray-100 border-gray-300';
  }
};

const getCommonPrefixLength = (a: string, b: string) => {
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  return i;
};

const getCommonSuffixLength = (a: string, b: string, prefixLen: number) => {
  let i = 0;
  while (i + prefixLen < a.length && i + prefixLen < b.length && a[a.length - 1 - i] === b[b.length - 1 - i]) i++;
  return i;
};

const getTrimmedDiffText = (oldValue: string, newValue: string) => {
  const prefixLen = getCommonPrefixLength(oldValue, newValue);
  const suffixLen = getCommonSuffixLength(oldValue, newValue, prefixLen);
  const trimText = (value: string) => {
    if (prefixLen + suffixLen >= value.length) return value.trim();
    return value.slice(prefixLen, value.length - suffixLen).trim();
  };
  const oldSnippet = trimText(oldValue);
  const newSnippet = trimText(newValue);
  if (!oldSnippet && !newSnippet) {
    return `${oldValue} → ${newValue}`;
  }
  return `${oldSnippet || '[刪除]'} → ${newSnippet || '[新增]'}`;
};

const DiffPopupInner: React.FC<DiffPopupInnerProps> = ({
  diff,
  onClose,
  onConfirm,
  onFlag,
  taskId,
  className = '',
}) => {
  const authUser = useAuthStore((s) => s.user);
  const [reviewer, setReviewer] = useState(diff.reviewed_by || authUser?.display_name || '');
  const [note, setNote] = useState('');
  const [oldCropFailed, setOldCropFailed] = useState(false);
  const [newCropFailed, setNewCropFailed] = useState(false);
  const [showCropPreview, setShowCropPreview] = useState(false);
  const [lightbox, setLightbox] = useState<{ url: string; label: string } | null>(null);

  const isImageDiff = diff.diff_type === DiffType.IMAGE_DIFF;
  const canFetchCrop = !!taskId;
  const oldCropUrl = diff.old_image_base64 || (canFetchCrop && diff.old_bbox ? buildAuthedUrl(`/api/compare/${taskId}/crop/${diff.id}/old`) : null);
  const newCropUrl = diff.new_image_base64 || (canFetchCrop && diff.new_bbox ? buildAuthedUrl(`/api/compare/${taskId}/crop/${diff.id}/new`) : null);
  const hasOldCropTarget = !!diff.old_image_base64 || (canFetchCrop && !!diff.old_bbox);
  const hasNewCropTarget = !!diff.new_image_base64 || (canFetchCrop && !!diff.new_bbox);
  const hasCropTarget = hasOldCropTarget || hasNewCropTarget;
  const showOldImage = showCropPreview && !!oldCropUrl && !oldCropFailed;
  const showNewImage = showCropPreview && !!newCropUrl && !newCropFailed;

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setLightbox(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightbox]);

  const handleConfirm = () => {
    onConfirm(diff.id, reviewer || undefined, note || undefined);
    onClose();
  };

  const handleFlag = () => {
    onFlag(diff.id, reviewer || undefined, note || undefined);
    onClose();
  };

  const handleCopy = (text: string) => {
    void navigator.clipboard.writeText(text);
  };

  const handleToggleCropPreview = () => {
    setShowCropPreview((current) => {
      if (current) {
        setLightbox(null);
      }
      return !current;
    });
  };

  const getEmptyMessage = (
    side: 'old' | 'new',
    hasSideCropTarget: boolean,
    cropFailed: boolean,
  ) => {
    if (!showCropPreview && hasSideCropTarget) {
      return '可顯示區域截圖';
    }
    if (showCropPreview && hasSideCropTarget && cropFailed) {
      return '無法載入截圖';
    }
    if (isImageDiff) {
      return side === 'old' ? '無原始文字（純視覺差異）' : '無修訂文字（純視覺差異）';
    }
    return side === 'old' ? '無原始內容' : '無修訂內容';
  };

  return (
    <div className={`relative w-full max-w-2xl max-h-[90vh] bg-white rounded-2xl shadow-2xl animate-fade-in flex flex-col ${className}`} style={{ resize: 'both', overflow: 'hidden', minWidth: '400px', minHeight: '300px' }}>
      {/* Fixed header */}
      <div className="flex items-center justify-between p-4 sm:p-6 border-b border-gray-200 flex-shrink-0">
        <div className="flex items-center flex-wrap gap-2">
          <div className={`px-3 py-1.5 rounded-full border ${getDiffColor(diff.diff_type)}`}>
            <span className="font-medium text-sm">{getDiffLabel(diff.diff_type)}</span>
          </div>
          <span className="text-xs sm:text-sm text-gray-500">ID: {diff.id}</span>
          {diff.reviewed ? (
            <div className="flex items-center space-x-1 px-2 py-1 bg-green-100 text-green-800 rounded-full">
              <CheckCircle size={12} />
              <span className="text-xs font-medium">已審核</span>
            </div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-2 rounded-full hover:bg-gray-100 transition-colors flex-shrink-0"
        >
          <X size={20} />
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto min-h-0 p-4 sm:p-6">
        <div className="mb-4 sm:mb-6">
          <h4 className="text-sm font-medium text-gray-500 mb-2">差異摘要</h4>
          <div
            className="rounded-2xl p-3 sm:p-4 mb-4"
            style={{
              backgroundColor: 'rgba(255, 246, 190, 0.16)',
              border: '1px solid rgba(255, 221, 120, 0.50)',
            }}
          >
            <p className="text-sm text-gray-900 whitespace-pre-wrap break-words">
              {diff.old_value && diff.new_value
                ? getTrimmedDiffText(diff.old_value, diff.new_value)
                : diff.new_value ?? diff.old_value ?? (isImageDiff
                  ? '偵測到表格或版面結構變更，請對照下方截圖確認差異。'
                  : diff.context)}
            </p>
          </div>

          <h4 className="text-sm font-medium text-gray-500 mb-2">位置</h4>
          <div className="flex items-center flex-wrap gap-2">
            <ExternalLink size={16} className="text-gray-400" />
            <span className="text-gray-700">{diff.context}</span>
            {diff.confidence ? (
              <span className="text-xs px-2 py-1 bg-primary-50 text-primary-700 rounded">
                信度: {(diff.confidence * 100).toFixed(1)}%
              </span>
            ) : null}
            {hasCropTarget ? (
              <button
                type="button"
                onClick={handleToggleCropPreview}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                  showCropPreview
                    ? 'border-gray-300 bg-gray-100 text-gray-700 hover:bg-gray-200'
                    : 'border-primary-200 bg-primary-50 text-primary-700 hover:bg-primary-100'
                }`}
              >
                {showCropPreview ? <EyeOff size={13} /> : <Eye size={13} />}
                {showCropPreview ? '隱藏截圖' : '顯示截圖'}
              </button>
            ) : null}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6 mb-4 sm:mb-6">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium text-red-600">原始內容</h4>
              {diff.old_value ? (
                <button
                  type="button"
                  onClick={() => handleCopy(diff.old_value ?? '')}
                  className="p-1 rounded hover:bg-gray-100 transition-colors"
                  title="複製"
                >
                  <Copy size={14} className="text-gray-400" />
                </button>
              ) : null}
            </div>
            <div className={`p-3 sm:p-4 rounded-lg border space-y-3 ${diff.old_value || showOldImage ? 'bg-red-50 border-red-200' : 'bg-gray-50 border-gray-200'}`}>
              {showOldImage && oldCropUrl ? (
                <button
                  type="button"
                  onClick={() => setLightbox({ url: oldCropUrl, label: '原始內容' })}
                  className="group relative block w-full cursor-zoom-in"
                  title="點擊放大"
                >
                  <img
                    src={oldCropUrl}
                    alt="原始區域截圖"
                    onError={() => setOldCropFailed(true)}
                    className="max-w-full h-auto rounded border border-red-100 bg-white"
                  />
                  <span className="absolute top-1 right-1 p-1 rounded bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity">
                    <Maximize2 size={14} />
                  </span>
                </button>
              ) : null}
              {diff.old_value ? (
                <>
                  {showOldImage ? <p className="text-xs text-gray-400 mt-2">OCR 判讀（僅供參考）</p> : null}
                  <pre className="text-sm text-gray-800 whitespace-pre-wrap break-words font-sans">
                    {diff.old_value}
                  </pre>
                </>
              ) : null}
              {!diff.old_value && !showOldImage ? (
                <p className="text-sm text-gray-500 italic">
                  {getEmptyMessage('old', hasOldCropTarget, oldCropFailed || (showCropPreview && !oldCropUrl))}
                </p>
              ) : null}
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium text-green-600">修訂內容</h4>
              {diff.new_value ? (
                <button
                  type="button"
                  onClick={() => handleCopy(diff.new_value ?? '')}
                  className="p-1 rounded hover:bg-gray-100 transition-colors"
                  title="複製"
                >
                  <Copy size={14} className="text-gray-400" />
                </button>
              ) : null}
            </div>
            <div className={`p-3 sm:p-4 rounded-lg border space-y-3 ${diff.new_value || showNewImage ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200'}`}>
              {showNewImage && newCropUrl ? (
                <button
                  type="button"
                  onClick={() => setLightbox({ url: newCropUrl, label: '修訂內容' })}
                  className="group relative block w-full cursor-zoom-in"
                  title="點擊放大"
                >
                  <img
                    src={newCropUrl}
                    alt="修訂區域截圖"
                    onError={() => setNewCropFailed(true)}
                    className="max-w-full h-auto rounded border border-green-100 bg-white"
                  />
                  <span className="absolute top-1 right-1 p-1 rounded bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity">
                    <Maximize2 size={14} />
                  </span>
                </button>
              ) : null}
              {diff.new_value ? (
                <>
                  {showNewImage ? <p className="text-xs text-gray-400 mt-2">OCR 判讀（僅供參考）</p> : null}
                  <pre className="text-sm text-gray-800 whitespace-pre-wrap break-words font-sans">
                    {diff.new_value}
                  </pre>
                </>
              ) : null}
              {!diff.new_value && !showNewImage ? (
                <p className="text-sm text-gray-500 italic">
                  {getEmptyMessage('new', hasNewCropTarget, newCropFailed || (showCropPreview && !newCropUrl))}
                </p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">審核人員</label>
            <input
              type="text"
              value={reviewer}
              onChange={(event) => setReviewer(event.target.value)}
              placeholder="輸入姓名或代號 (選填)"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">備註</label>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="輸入審核備註 (選填)"
              rows={2}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
        </div>
      </div>

      {/* Fixed footer - always visible */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between p-4 sm:p-6 gap-3 border-t border-gray-200 bg-[#F5F5F5] rounded-b-2xl flex-shrink-0">
        <div className="text-sm text-gray-500">
          {diff.reviewed ? (
            <div className="flex items-center space-x-2">
              <CheckCircle size={14} className="text-green-500" />
              <span>已由 {diff.reviewed_by} 於 {diff.reviewed_at ? new Date(diff.reviewed_at).toLocaleString() : '未知時間'} 審核</span>
            </div>
          ) : (
            <span>尚未審核</span>
          )}
        </div>
        <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
          <button
            type="button"
            onClick={onClose}
            className="px-3 sm:px-4 py-2 sm:py-2.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm"
          >
            關閉
          </button>
          <button
            type="button"
            onClick={handleFlag}
            className="px-3 sm:px-4 py-2 sm:py-2.5 border border-red-300 text-red-700 bg-red-50 rounded-lg hover:bg-red-100 transition-colors flex items-center space-x-1 sm:space-x-2 text-sm"
          >
            <Flag size={16} />
            <span>標記問題</span>
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            className="px-3 sm:px-4 py-2 sm:py-2.5 bg-diff-added text-white rounded-lg hover:bg-emerald-600 transition-colors flex items-center space-x-1 sm:space-x-2 text-sm"
          >
            <CheckCircle size={16} />
            <span>確認此修改</span>
          </button>
        </div>
      </div>

      {lightbox ? (
        <div
          className="fixed inset-0 z-[60] flex flex-col bg-black/80"
          onClick={() => setLightbox(null)}
        >
          <div
            className="flex items-center justify-between px-4 py-3 text-white"
            onClick={(event) => event.stopPropagation()}
          >
            <span className="text-sm font-medium">{lightbox.label}</span>
            <button
              type="button"
              onClick={() => setLightbox(null)}
              className="p-2 rounded-full hover:bg-white/10 transition-colors"
              title="關閉 (Esc)"
            >
              <X size={20} />
            </button>
          </div>
          <div
            className="flex-1 min-h-0 overflow-hidden"
            onClick={(event) => event.stopPropagation()}
          >
            <TransformWrapper
              initialScale={1}
              minScale={0.5}
              maxScale={10}
              wheel={{ step: 0.15 }}
              doubleClick={{ mode: 'reset' }}
            >
              {({ zoomIn, zoomOut, resetTransform }) => (
                <>
                  <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex items-center space-x-2 bg-black/60 text-white rounded-full px-2 py-1">
                    <button
                      type="button"
                      onClick={() => zoomOut()}
                      className="p-2 rounded-full hover:bg-white/10"
                      title="縮小"
                    >
                      <Minus size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => resetTransform()}
                      className="p-2 rounded-full hover:bg-white/10"
                      title="重置"
                    >
                      <RotateCcw size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => zoomIn()}
                      className="p-2 rounded-full hover:bg-white/10"
                      title="放大"
                    >
                      <Plus size={16} />
                    </button>
                  </div>
                  <TransformComponent
                    wrapperClass="!w-full !h-full"
                    contentClass="!w-full !h-full flex items-center justify-center"
                  >
                    <img
                      src={lightbox.url}
                      alt={lightbox.label}
                      className="max-w-full max-h-full object-contain select-none"
                      draggable={false}
                    />
                  </TransformComponent>
                </>
              )}
            </TransformWrapper>
          </div>
        </div>
      ) : null}
    </div>
  );
};

const DiffPopup: React.FC<DiffPopupProps> = (props) => {
  const { diff, isOpen, onClose } = props;

  if (!isOpen || !diff) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/45"
        onClick={onClose}
      />
      <DiffPopupInner key={diff.id} {...props} diff={diff} />
    </div>
  );
};

export default DiffPopup;
