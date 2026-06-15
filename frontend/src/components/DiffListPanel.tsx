import React from 'react';
import { CheckCircle } from 'lucide-react';
import { DiffItem, DiffType } from '../services/types';

interface DiffListPanelProps {
  diffItems: DiffItem[];
  selectedDiffId: string | null;
  onDiffSelect: (diffId: string) => void;
  className?: string;
}

const getDiffIcon = () => (
  <div className="w-3 h-3 rounded-full bg-diff-highlight ring-1 ring-white" />
);

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

  return (
    <div className={`flex flex-col h-full overflow-hidden ${className}`}>
      <div className="flex-1 overflow-auto divide-y divide-gray-100">
        {diffItems.map((item) => {
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
                <div className="flex-shrink-0 mt-1">
                  {getDiffIcon()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center space-x-2 mb-1">
                    <span className="text-sm font-medium text-gray-900">
                      {getDiffLabel(item.diff_type)}
                    </span>
                    <span className="text-xs text-gray-500">
                      {item.context}
                    </span>
                    {item.reviewed && (
                      <CheckCircle className="text-green-500" size={14} />
                    )}
                  </div>

                  <div className="mb-2">
                    <div className="text-xs text-gray-500 mb-1">差異摘要</div>
                    <p className="text-sm text-gray-800 line-clamp-2">
                      {item.diff_type === DiffType.IMAGE_DIFF
                        ? '表格或版面結構變更，請對照截圖核對'
                        : item.old_value && item.new_value
                        ? getTrimmedDiffText(item.old_value, item.new_value)
                        : item.new_value ?? item.old_value ?? item.context}
                    </p>
                  </div>

                  <div className="space-y-1">
                    {item.old_value && (
                      <div className="flex items-center">
                        <span className="text-xs text-red-600 bg-red-50 px-1.5 py-0.5 rounded mr-2 flex-shrink-0">
                          舊值
                        </span>
                        <p className={`text-sm ${item.reviewed ? 'text-gray-500' : 'text-gray-700'} line-clamp-2`}>
                          {item.old_value}
                        </p>
                      </div>
                    )}
                    
                    {item.new_value && (
                      <div className="flex items-center">
                        <span className="text-xs text-green-600 bg-green-50 px-1.5 py-0.5 rounded mr-2 flex-shrink-0">
                          新值
                        </span>
                        <p className={`text-sm ${item.reviewed ? 'text-gray-500' : 'text-gray-700'} line-clamp-2`}>
                          {item.new_value}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DiffListPanel;
