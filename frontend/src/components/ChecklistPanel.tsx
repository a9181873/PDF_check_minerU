import React, { useState } from 'react';
import { CheckCircle, XCircle, AlertTriangle, Search, Download } from 'lucide-react';
import { ChecklistItem, CheckStatus } from '../services/types';
import { useCompareStore } from '../stores/compareStore';

interface ChecklistPanelProps {
  items: ChecklistItem[];
  comparisonId: string;
  onItemUpdate?: (itemId: string, updates: Partial<ChecklistItem>) => void;
  className?: string;
}

const ChecklistPanel: React.FC<ChecklistPanelProps> = ({
  items,
  comparisonId,
  onItemUpdate,
  className = '',
}) => {
  const [filter, setFilter] = useState<CheckStatus | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const { getDiffById } = useCompareStore();

  const filteredItems = items.filter(item => {
    const matchesFilter = filter === 'all' || item.status === filter;
    const matchesSearch = searchQuery === '' || 
      item.item_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.search_keyword.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.expected_old?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.expected_new?.toLowerCase().includes(searchQuery.toLowerCase());
    
    return matchesFilter && matchesSearch;
  });

  const getStatusIcon = (status: CheckStatus) => {
    switch (status) {
      case CheckStatus.CONFIRMED:
        return <CheckCircle size={16} className="text-green-500" />;
      case CheckStatus.ANOMALY:
        return <XCircle size={16} className="text-red-500" />;
      case CheckStatus.MISSING:
        return <AlertTriangle size={16} className="text-gray-500" />;
      case CheckStatus.PENDING:
        return <div className="w-4 h-4 rounded-full border-2 border-amber-500 border-t-transparent animate-spin" />;
      default:
        return null;
    }
  };

  const getStatusColor = (status: CheckStatus) => {
    switch (status) {
      case CheckStatus.CONFIRMED:
        return 'bg-green-100 text-green-800 border-green-200';
      case CheckStatus.ANOMALY:
        return 'bg-red-100 text-red-800 border-red-200';
      case CheckStatus.MISSING:
        return 'bg-gray-100 text-gray-800 border-gray-200';
      case CheckStatus.PENDING:
        return 'bg-amber-100 text-amber-800 border-amber-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const getStatusText = (status: CheckStatus) => {
    switch (status) {
      case CheckStatus.CONFIRMED:
        return '已確認';
      case CheckStatus.ANOMALY:
        return '標記問題';
      case CheckStatus.MISSING:
        return '未找到';
      case CheckStatus.PENDING:
        return '待處理';
      default:
        return '未知';
    }
  };

  const handleStatusChange = (itemId: string, newStatus: CheckStatus) => {
    onItemUpdate?.(itemId, { status: newStatus });
  };

  const handleExport = () => {
    const csvRows = [
      ['item_id', 'check_type', 'search_keyword', 'expected_old', 'expected_new', 'page_hint', 'status', 'matched_diff_id', 'note'],
      ...items.map(item => [
        item.item_id,
        item.check_type,
        item.search_keyword,
        item.expected_old || '',
        item.expected_new || '',
        item.page_hint || '',
        item.status,
        item.matched_diff_id || '',
        item.note || '',
      ])
    ];

    const csvContent = csvRows.map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `checklist_${comparisonId}_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-gray-900">核對清單</h3>
          <p className="text-sm text-gray-600">
            總計 {items.length} 個項目 • 已確認 {items.filter(i => i.status === CheckStatus.CONFIRMED).length} 個
          </p>
        </div>
        <button
          onClick={handleExport}
          className="flex items-center space-x-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
        >
          <Download size={16} />
          <span>匯出 CSV</span>
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center space-x-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜尋項目 ID 或關鍵字..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>

        <div className="flex space-x-2">
          <button
            onClick={() => setFilter('all')}
            className={`px-4 py-2.5 rounded-lg transition-colors ${filter === 'all' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
          >
            全部
          </button>
          <button
            onClick={() => setFilter(CheckStatus.PENDING)}
            className={`px-4 py-2.5 rounded-lg transition-colors flex items-center space-x-2 ${filter === CheckStatus.PENDING ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
          >
            {getStatusIcon(CheckStatus.PENDING)}
            <span>待處理</span>
          </button>
          <button
            onClick={() => setFilter(CheckStatus.CONFIRMED)}
            className={`px-4 py-2.5 rounded-lg transition-colors flex items-center space-x-2 ${filter === CheckStatus.CONFIRMED ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
          >
            {getStatusIcon(CheckStatus.CONFIRMED)}
            <span>已確認</span>
          </button>
          <button
            onClick={() => setFilter(CheckStatus.ANOMALY)}
            className={`px-4 py-2.5 rounded-lg transition-colors flex items-center space-x-2 ${filter === CheckStatus.ANOMALY ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
            title="人工標記需要追查的項目"
          >
            {getStatusIcon(CheckStatus.ANOMALY)}
            <span>標記問題</span>
          </button>
        </div>
      </div>

      {/* Items list */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  狀態
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  項目 ID
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  關鍵字
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  預期值
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  實際值
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  操作
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {filteredItems.map((item) => {
                const matchedDiff = item.matched_diff_id ? getDiffById(item.matched_diff_id) : null;
                
                return (
                  <tr key={item.item_id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className={`inline-flex items-center px-3 py-1 rounded-full border ${getStatusColor(item.status)}`}>
                        {getStatusIcon(item.status)}
                        <span className="ml-2 text-sm font-medium">{getStatusText(item.status)}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm font-medium text-gray-900">{item.item_id}</div>
                      <div className="text-xs text-gray-500">{item.check_type}</div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-900">{item.search_keyword}</div>
                      {item.page_hint && (
                        <div className="text-xs text-gray-500">頁面: {item.page_hint}</div>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <div className="space-y-1">
                        {item.expected_old && (
                          <div className="text-xs">
                            <span className="text-red-600">舊:</span> {item.expected_old}
                          </div>
                        )}
                        {item.expected_new && (
                          <div className="text-xs">
                            <span className="text-green-600">新:</span> {item.expected_new}
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {matchedDiff ? (
                        <div className="space-y-1">
                          <div className="text-xs">
                            <span className="text-red-600">舊:</span> {matchedDiff.old_value || '無'}
                          </div>
                          <div className="text-xs">
                            <span className="text-green-600">新:</span> {matchedDiff.new_value || '無'}
                          </div>
                          <div className="text-xs text-gray-500">
                            差異 ID: {matchedDiff.id}
                          </div>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-500 italic">未匹配</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center space-x-2">
                        <button
                          onClick={() => handleStatusChange(item.item_id, CheckStatus.CONFIRMED)}
                          className="px-3 py-1.5 bg-green-100 text-green-700 rounded-lg hover:bg-green-200 transition-colors text-sm"
                          title="標記為已確認"
                        >
                          確認
                        </button>
                        <button
                          onClick={() => handleStatusChange(item.item_id, CheckStatus.ANOMALY)}
                          className="px-3 py-1.5 bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors text-sm"
                          title="標記為需要追查"
                        >
                          標記問題
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {filteredItems.length === 0 && (
          <div className="p-8 text-center">
            <div className="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
              <Search className="text-gray-400" size={24} />
            </div>
            <p className="text-gray-600">找不到符合條件的項目</p>
            <p className="text-gray-500 text-sm mt-1">請嘗試不同的搜尋條件或篩選器</p>
          </div>
        )}
      </div>

      {/* Summary */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-primary-50 p-4 rounded-lg">
          <div className="text-sm text-primary-700">總項目</div>
          <div className="text-2xl font-bold text-primary-900">{items.length}</div>
        </div>
        <div className="bg-green-50 p-4 rounded-lg">
          <div className="text-sm text-green-700">已確認</div>
          <div className="text-2xl font-bold text-green-900">
            {items.filter(i => i.status === CheckStatus.CONFIRMED).length}
          </div>
        </div>
        <div className="bg-red-50 p-4 rounded-lg">
          <div className="text-sm text-red-700">標記問題</div>
          <div className="text-2xl font-bold text-red-900">
            {items.filter(i => i.status === CheckStatus.ANOMALY).length}
          </div>
        </div>
        <div className="bg-[#F5F5F5] p-4 rounded-lg">
          <div className="text-sm text-gray-600">待處理</div>
          <div className="text-2xl font-bold text-gray-900">
            {items.filter(i => i.status === CheckStatus.PENDING).length}
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChecklistPanel;
