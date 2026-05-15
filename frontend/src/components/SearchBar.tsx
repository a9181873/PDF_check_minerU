import React, { useState, useEffect, useCallback } from 'react';
import { Search, Filter, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import { DiffItem, DiffType } from '../services/types';

interface SearchBarProps {
  diffItems: DiffItem[];
  searchQuery: string;
  onSearchChange: (query: string) => void;
  selectedDiffId: string | null;
  onDiffSelect: (diffId: string) => void;
  className?: string;
}

const SearchBar: React.FC<SearchBarProps> = ({
  diffItems,
  searchQuery,
  onSearchChange,
  selectedDiffId,
  onDiffSelect,
  className = '',
}) => {
  const [inputValue, setInputValue] = useState(searchQuery);
  const [showResults, setShowResults] = useState(false);
  const [filterType, setFilterType] = useState<DiffType | 'all'>('all');

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      if (inputValue !== searchQuery) {
        onSearchChange(inputValue);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [inputValue, searchQuery, onSearchChange]);

  // Filter and search items
  const filteredItems = diffItems.filter(item => {
    const q = inputValue.toLowerCase();
    const bbox = item.new_bbox || item.old_bbox;
    const matchesSearch = inputValue === '' || 
      item.old_value?.toLowerCase().includes(q) ||
      item.new_value?.toLowerCase().includes(q) ||
      item.context?.toLowerCase().includes(q) ||
      item.id.toLowerCase().includes(q) ||
      (item.reviewed_by || '').toLowerCase().includes(q) ||
      (bbox ? `p${bbox.page}`.includes(q) || `第${bbox.page}頁`.includes(q) || String(bbox.page) === q : false);
    
    const matchesFilter = filterType === 'all' || item.diff_type === filterType;
    
    return matchesSearch && matchesFilter;
  });

  const getDiffIcon = (type: DiffType) => {
    switch (type) {
      case DiffType.ADDED:
        return <div className="w-3 h-3 rounded-full bg-diff-added" />;
      case DiffType.DELETED:
        return <div className="w-3 h-3 rounded-full bg-diff-deleted" />;
      case DiffType.NUMBER_MODIFIED:
        return <div className="w-3 h-3 rounded-full bg-diff-modified" />;
      case DiffType.TEXT_MODIFIED:
        return <div className="w-3 h-3 rounded-full bg-diff-text" />;
      default:
        return <div className="w-3 h-3 rounded-full bg-gray-400" />;
    }
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
      default:
        return '修改';
    }
  };

  const handleResultClick = useCallback((diffId: string) => {
    onDiffSelect(diffId);
    setShowResults(false);
  }, [onDiffSelect]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setShowResults(false);
    } else if (e.key === 'Enter' && filteredItems.length > 0) {
      handleResultClick(filteredItems[0].id);
    }
  };

  return (
    <div className={`relative ${className}`}>
      <div className="flex items-center space-x-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onFocus={() => setShowResults(true)}
            onKeyDown={handleKeyDown}
            placeholder="搜尋差異內容 (文字、數值、頁面)..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all"
          />
          
          {inputValue && (
            <button
              onClick={() => {
                setInputValue('');
                onSearchChange('');
              }}
              className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <XCircle size={18} />
            </button>
          )}
        </div>

        <div className="relative">
          <button
            onClick={() => setFilterType(prev => prev === 'all' ? DiffType.ADDED : prev === DiffType.ADDED ? DiffType.DELETED : prev === DiffType.DELETED ? DiffType.NUMBER_MODIFIED : prev === DiffType.NUMBER_MODIFIED ? DiffType.TEXT_MODIFIED : 'all')}
            className="flex items-center space-x-2 px-3 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            title="篩選差異類型"
          >
            <Filter size={16} />
            <span className="text-sm font-medium">
              {filterType === 'all' ? '所有類型' : getDiffLabel(filterType)}
            </span>
          </button>
        </div>
      </div>

      {/* Search results dropdown */}
      {showResults && filteredItems.length > 0 && (
        <div className="absolute z-50 w-full mt-2 bg-white rounded-lg shadow-large border border-gray-200 max-h-96 overflow-auto">
          <div className="p-2 border-b border-gray-200 bg-gray-50">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-700">
                找到 {filteredItems.length} 個結果
              </span>
              <button
                onClick={() => setShowResults(false)}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                關閉
              </button>
            </div>
          </div>
          
          <div className="divide-y divide-gray-100">
            {filteredItems.map((item) => (
              <div
                key={item.id}
                className={`p-3 cursor-pointer hover:bg-gray-50 transition-colors ${selectedDiffId === item.id ? 'bg-primary-50' : ''}`}
                onClick={() => handleResultClick(item.id)}
              >
                <div className="flex items-start space-x-3">
                  <div className="flex-shrink-0 mt-1">
                    {getDiffIcon(item.diff_type)}
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
                    
                    <div className="space-y-1">
                      {item.old_value && (
                        <div className="flex items-center">
                          <span className="text-xs text-red-600 bg-red-50 px-1.5 py-0.5 rounded mr-2">
                            舊值
                          </span>
                          <p className="text-sm text-gray-700 truncate">
                            {item.old_value}
                          </p>
                        </div>
                      )}
                      
                      {item.new_value && (
                        <div className="flex items-center">
                          <span className="text-xs text-green-600 bg-green-50 px-1.5 py-0.5 rounded mr-2">
                            新值
                          </span>
                          <p className="text-sm text-gray-700 truncate">
                            {item.new_value}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                  
                  <div className="flex-shrink-0">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleResultClick(item.id);
                      }}
                      className="text-xs px-2 py-1 bg-primary-100 text-primary-700 rounded hover:bg-primary-200 transition-colors"
                    >
                      跳轉
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {showResults && inputValue && filteredItems.length === 0 && (
        <div className="absolute z-50 w-full mt-2 bg-white rounded-lg shadow-large border border-gray-200 p-4">
          <div className="flex items-center justify-center space-x-2 text-gray-500">
            <AlertCircle size={18} />
            <span>未找到符合「{inputValue}」的差異</span>
          </div>
        </div>
      )}

      {/* Click outside to close */}
      {showResults && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setShowResults(false)}
        />
      )}
    </div>
  );
};

export default SearchBar;
