import React from 'react';
import { DiffItem, DiffType } from '../services/types';
import { getTrimmedDiffText } from '../utils/diffHelpers';

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
  /** Which document this overlay is drawn over. The old PDF must highlight at the
   *  OLD bbox and the new PDF at the NEW bbox — a MODIFIED item has different
   *  coordinates on each side, so sharing one bbox misplaces the old-side boxes. */
  side?: 'old' | 'new';
}

/** The bbox for THIS side only — no cross-side fallback. An item with no bbox on
 *  this side has no location here (an ADDED item exists only in new; a DELETED only
 *  in old), so it must not be drawn: falling back to the other side's bbox would
 *  paint an ADDED box onto the old PDF (or a DELETED box onto the new) at the wrong
 *  coordinates. MODIFIED/IMAGE_DIFF items carry both bboxes, so they draw on both. */
const pickBbox = (diff: DiffItem, side: 'old' | 'new') =>
  side === 'old' ? diff.old_bbox : diff.new_bbox;

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
      return '表格/版面';
    default:
      return '修改';
  }
};

const DiffOverlay: React.FC<DiffOverlayProps> = ({
  diffItems,
  pageNumber,
  pdfPageWidth,
  pdfPageHeight,
  selectedDiffId = null,
  onDiffClick,
  showLabels = true,
  side = 'new',
}) => {
  // Filter diffs for this specific page
  const pageDiffs = diffItems.filter((diff) => {
    const bbox = pickBbox(diff, side);
    return bbox && bbox.page === pageNumber;
  });

  if (pageDiffs.length === 0) {
    return null;
  }

  return (
    // inset-0 always fills the parent .relative div exactly — no stored pixel dimensions needed
    <div className="absolute inset-0 pointer-events-none">
      {pageDiffs.map((diff) => {
        const bbox = pickBbox(diff, side);
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
