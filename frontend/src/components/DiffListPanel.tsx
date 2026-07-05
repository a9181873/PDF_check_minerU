import React from 'react';
import { CheckCircle } from 'lucide-react';
import { DiffItem, DiffType } from '../services/types';
import { getTrimmedDiffText } from '../utils/diffHelpers';

interface DiffListPanelProps {
  diffItems: DiffItem[];
  selectedDiffId: string | null;
  onDiffSelect: (diffId: string) => void;
  className?: string;
}

const getDiffIcon = () => (
  <div className="w-3 h-3 rounded-full bg-diff-highlight ring-1 ring-white" />
);

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

const DiffListPanel: React.FC<DiffListPanelProps> = ({
  diffItems,
  selectedDiffId,
  onDiffSelect,
  className = '',
}) => {
  if (diffItems.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center h-full text-gray-500 space-y-2 p-6 ${className}`}>
        <p>目前沒有差異項目</p>
      </div>
    );
  }

  const isVisualReview = (item: DiffItem) =>
    item.review_lane === 'needs_visual_review' || item.diff_type === DiffType.IMAGE_DIFF;
  const contentItems = diffItems.filter((item) => !isVisualReview(item));
  const visualReviewItems = diffItems.filter(isVisualReview);

  const renderItem = (item: DiffItem) => {
    const isSelected = selectedDiffId === item.id;
    return (
      <div
        key={item.id}
        className={`p-3 cursor-pointer transition-colors ${
          isSelected ? 'bg-primary-50 border-l-4 border-l-primary-500' : 'hover:bg-gray-50 border-l-4 border-l-transparent'
        } ${item.reviewed ? 'opacity-60 saturate-50' : ''}`}
        onClick={() => onDiffSelect(item.id)}
      >
        <div className="flex items-start space-x-3">
          <div className="flex-shrink-0 mt-1">{getDiffIcon()}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="text-sm font-medium text-gray-900">{getDiffLabel(item.diff_type)}</span>
              {item.risk_level && (
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                  item.risk_level === 'critical' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                }`}>
                  {item.risk_level === 'critical' ? '關鍵' : item.risk_level === 'high' ? '高風險' : '一般'}
                </span>
              )}
              <span className="text-xs text-gray-500">{item.context}</span>
              {item.reviewed && <CheckCircle className="text-green-500" size={14} />}
            </div>
            <div className="mb-2">
              <div className="text-xs text-gray-500 mb-1">差異摘要</div>
              <p className="text-sm text-gray-800 line-clamp-2">
                {item.review_lane === 'needs_visual_review' || item.diff_type === DiffType.IMAGE_DIFF
                  ? '模型無法可靠解讀，但此區域確有變更，請人工核對新舊畫面'
                  : item.old_value && item.new_value
                  ? getTrimmedDiffText(item.old_value, item.new_value)
                  : item.new_value ?? item.old_value ?? item.context}
              </p>
            </div>
            <div className="space-y-1">
              {item.old_value && <div className="flex items-center"><span className="text-xs text-red-600 bg-red-50 px-1.5 py-0.5 rounded mr-2 flex-shrink-0">舊值</span><p className="text-sm text-gray-700 line-clamp-2">{item.old_value}</p></div>}
              {item.new_value && <div className="flex items-center"><span className="text-xs text-green-600 bg-green-50 px-1.5 py-0.5 rounded mr-2 flex-shrink-0">新值</span><p className="text-sm text-gray-700 line-clamp-2">{item.new_value}</p></div>}
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className={`flex flex-col h-full overflow-hidden ${className}`}>
      <div className="flex-1 overflow-auto">
        {contentItems.length > 0 && <div className="sticky top-0 z-10 bg-white px-3 py-2 text-xs font-semibold text-gray-600 border-b">正式內容差異（{contentItems.length}）</div>}
        <div className="divide-y divide-gray-100">{contentItems.map(renderItem)}</div>
        {visualReviewItems.length > 0 && <div className="sticky top-0 z-10 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800 border-y border-amber-200">待人工判讀區域（{visualReviewItems.length}）</div>}
        <div className="divide-y divide-gray-100">{visualReviewItems.map(renderItem)}</div>
      </div>
    </div>
  );
};

export default DiffListPanel;
