import React from 'react';
import { DiffItem, DiffType } from '../services/types';

interface DiffOverlayProps {
  diffItems: DiffItem[];
  /** The page number this overlay is scoped to */
  pageNumber: number;
  /** Original PDF page width in PDF points (usually 595 for A4) */
  pdfPageWidth: number;
  /** Original PDF page height in PDF points (usually 842 for A4) */
  pdfPageHeight: number;
  selectedDiffId?: string | null;
  onDiffClick?: (diff: DiffItem) => void;
  showLabels?: boolean;
}

const getDiffColor = () => {
  return 'diff-overlay-highlight';
};

const getDiffLabel = (type: DiffType) => {
  switch (type) {
    case DiffType.ADDED:
      return '新增';
    case DiffType.DELETED:
      return '刪除';
    case DiffType.NUMBER_MODIFIED:
      return '數值修改';
    case DiffType.TEXT_MODIFIED:
      return '文字修改';
    case DiffType.IMAGE_DIFF:
      return '視覺差異';
    default:
      return '修改';
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

const DiffOverlay: React.FC<DiffOverlayProps> = ({
  diffItems,
  pageNumber,
  pdfPageWidth,
  pdfPageHeight,
  selectedDiffId = null,
  onDiffClick,
  showLabels = true,
}) => {
  // Filter diffs for this specific page
  const pageDiffs = diffItems.filter((diff) => {
    const bbox = diff.new_bbox || diff.old_bbox;
    return bbox && bbox.page === pageNumber;
  });

  if (pageDiffs.length === 0) {
    return null;
  }

  return (
    // inset-0 always fills the parent .relative div exactly — no stored pixel dimensions needed
    <div className="absolute inset-0 pointer-events-none">
      {pageDiffs.map((diff) => {
        const bbox = diff.new_bbox || diff.old_bbox;
        if (!bbox) return null;

        // Use % so the overlay stays accurate regardless of scale or transition state.
        // PDF Y axis is bottom-up; CSS Y axis is top-down.
        const left = (bbox.x0 / pdfPageWidth) * 100;
        const top = ((pdfPageHeight - bbox.y1) / pdfPageHeight) * 100;
        const width = ((bbox.x1 - bbox.x0) / pdfPageWidth) * 100;
        const height = ((bbox.y1 - bbox.y0) / pdfPageHeight) * 100;

        const colorClass = getDiffColor();
        const label = getDiffLabel(diff.diff_type);
        const isSelected = selectedDiffId === diff.id;

        const titleText =
          diff.diff_type === DiffType.IMAGE_DIFF
            ? `${label} - ${diff.context || ''}`.trim()
            : `${label}: ${diff.old_value && diff.new_value ? getTrimmedDiffText(diff.old_value, diff.new_value) : `${diff.old_value || ''} → ${diff.new_value || ''}`}`;

        return (
          <div
            key={diff.id}
            id={`diff-overlay-${diff.id}`}
            className={`${colorClass} cursor-pointer group pointer-events-auto ${isSelected ? 'is-selected' : ''}`}
            style={{
              position: 'absolute',
              left: `${left}%`,
              top: `${top}%`,
              width: `${Math.max(width, 0.3)}%`,
              height: `${Math.max(height, 0.3)}%`,
            }}
            onClick={() => onDiffClick?.(diff)}
            title={titleText}
          >
            {showLabels && (
              <div className="absolute inset-x-0 top-0 pointer-events-none px-1 pt-1">
                <div className="bg-white/90 text-[10px] text-gray-900 rounded-full px-1.5 py-0.5 shadow-sm max-w-full overflow-hidden text-ellipsis whitespace-nowrap">
                  {titleText}
                </div>
              </div>
            )}
            {/* Tooltip on hover */}
            <div className="absolute -top-8 left-1/2 transform -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-20">
              <div className="bg-gray-900 text-white text-xs py-1 px-2 rounded whitespace-nowrap max-w-[200px] truncate">
                {label}
              </div>
              <div className="absolute -bottom-1 left-1/2 transform -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-gray-900" />
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default DiffOverlay;
