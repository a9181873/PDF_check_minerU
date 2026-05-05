import React, { useCallback, useEffect, useRef } from 'react';
import { PanelLeftClose, PanelLeftOpen, ExternalLink } from 'lucide-react';
import { useCrossWindowSync } from '../hooks/useCrossWindowSync';

interface SyncScrollContainerProps {
  leftContent: React.ReactNode;
  rightContent: React.ReactNode;
  syncEnabled?: boolean;
  onSyncToggle?: (enabled: boolean) => void;
  leftHidden?: boolean;
  onLeftHiddenToggle?: (hidden: boolean) => void;
  taskId?: string;
  className?: string;
}

const SyncScrollContainer: React.FC<SyncScrollContainerProps> = ({
  leftContent,
  rightContent,
  syncEnabled = true,
  onSyncToggle,
  leftHidden = false,
  onLeftHiddenToggle,
  taskId,
  className = '',
}) => {
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const isSyncingRef = useRef(false);
  const unlockTimerRef = useRef<number | null>(null);

  const { broadcastScroll } = useCrossWindowSync(taskId || null);

  // Sync scroll positions
  const syncScroll = useCallback((source: 'left' | 'right', target: 'left' | 'right') => {
    if (!syncEnabled || isSyncingRef.current) return;

    isSyncingRef.current = true;

    const sourceEl = source === 'left' ? leftRef.current : rightRef.current;
    const targetEl = target === 'left' ? leftRef.current : rightRef.current;

    if (sourceEl && targetEl) {
      const sourceScrollTop = sourceEl.scrollTop;
      const sourceScrollHeight = sourceEl.scrollHeight;
      const sourceClientHeight = sourceEl.clientHeight;
      const targetScrollHeight = targetEl.scrollHeight;
      const targetClientHeight = targetEl.clientHeight;
      const sourceScrollable = sourceScrollHeight - sourceClientHeight;
      const targetScrollable = targetScrollHeight - targetClientHeight;

      if (sourceScrollable > 0 && targetScrollable > 0) {
        const sourceRatio = sourceScrollTop / sourceScrollable;
        targetEl.scrollTop = sourceRatio * targetScrollable;
        broadcastScroll(source === 'left' ? 'old' : 'new', sourceRatio);
      }
    }

    if (unlockTimerRef.current) {
      window.clearTimeout(unlockTimerRef.current);
    }
    unlockTimerRef.current = window.setTimeout(() => {
      isSyncingRef.current = false;
    }, 150);
  }, [syncEnabled]);

  useEffect(() => {
    const leftEl = leftRef.current;
    const rightEl = rightRef.current;
    
    const handleLeftScroll = () => syncScroll('left', 'right');
    const handleRightScroll = () => syncScroll('right', 'left');
    
    if (leftEl) {
      leftEl.addEventListener('scroll', handleLeftScroll);
    }
    
    if (rightEl) {
      rightEl.addEventListener('scroll', handleRightScroll);
    }
    
    return () => {
      if (leftEl) {
        leftEl.removeEventListener('scroll', handleLeftScroll);
      }
      if (rightEl) {
        rightEl.removeEventListener('scroll', handleRightScroll);
      }
      if (unlockTimerRef.current) {
        window.clearTimeout(unlockTimerRef.current);
      }
    };
  }, [syncScroll]);

  // Listen for incoming cross-window scroll events
  useEffect(() => {
    const handleCrossWindowScroll = (e: Event) => {
      const customEvent = e as CustomEvent<{ source: 'old' | 'new', ratio: number }>;
      const { source, ratio } = customEvent.detail;
      
      const targetEl = source === 'old' ? rightRef.current : leftRef.current;
      const otherEl = source === 'old' ? leftRef.current : rightRef.current;
      
      if (targetEl) {
        isSyncingRef.current = true;
        const scrollable = targetEl.scrollHeight - targetEl.clientHeight;
        if (scrollable > 0) targetEl.scrollTop = ratio * scrollable;
      }
      if (otherEl && source === 'old') {
        const scrollable = otherEl.scrollHeight - otherEl.clientHeight;
        if (scrollable > 0) otherEl.scrollTop = ratio * scrollable;
      }
      if (otherEl && source === 'new') {
        const scrollable = otherEl.scrollHeight - otherEl.clientHeight;
         if (scrollable > 0) otherEl.scrollTop = ratio * scrollable;
      }

      if (unlockTimerRef.current) window.clearTimeout(unlockTimerRef.current);
      unlockTimerRef.current = window.setTimeout(() => { isSyncingRef.current = false; }, 150);
    };

    window.addEventListener('cross-window-scroll', handleCrossWindowScroll);
    return () => window.removeEventListener('cross-window-scroll', handleCrossWindowScroll);
  }, []);

  const handleToggleLeftPanel = () => {
    onLeftHiddenToggle?.(!leftHidden);
  };

  const handleToggleSync = () => {
    onSyncToggle?.(!syncEnabled);
  };

  return (
    <div className={`flex h-full ${className}`}>
      {/* Left panel */}
      <div
        className={`transition-all duration-300 ${leftHidden ? 'w-0 overflow-hidden' : 'w-1/2'}`}
      >
        <div className="h-full flex flex-col">
          <div className="flex items-center justify-between p-3 bg-gray-100 border-b border-gray-300">
            <div className="flex items-center space-x-2">
              <span className="font-medium text-gray-700">舊版文件</span>
              <div className="text-xs bg-gray-300 text-gray-700 px-2 py-0.5 rounded">
                原始版本
              </div>
            </div>
            <div className="flex items-center space-x-2">
              <button
                onClick={handleToggleSync}
                className={`p-2 rounded transition-colors ${syncEnabled ? 'bg-primary-100 text-primary-700' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'}`}
                title={syncEnabled ? '同步滾動啟用' : '同步滾動停用'}
              >
                <div className="flex items-center space-x-1">
                  <div className={`w-2 h-2 rounded-full ${syncEnabled ? 'bg-green-500' : 'bg-gray-400'}`} />
                  <span className="text-xs">{syncEnabled ? '同步中' : '未同步'}</span>
                </div>
              </button>
              <button
                onClick={handleToggleLeftPanel}
                className="p-2 rounded hover:bg-gray-200 transition-colors"
                title="隱藏左側面板"
              >
                <PanelLeftClose size={18} />
              </button>
              <button
                onClick={() => taskId && window.open(`/popout/${taskId}/old`, '_blank', 'width=800,height=900,menubar=no,toolbar=no,location=no')}
                className="p-2 rounded hover:bg-gray-200 transition-colors text-gray-500"
                title="用新視窗彈出 (雙螢幕模式)"
              >
                <ExternalLink size={18} />
              </button>
            </div>
          </div>
          <div
            ref={leftRef}
            className="flex-1 overflow-auto scroll-sync"
          >
            <div className="p-4">
              {leftContent}
            </div>
          </div>
        </div>
      </div>

      {/* Divider handle */}
      <div className="relative group">
        <button
          onClick={handleToggleLeftPanel}
          className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 z-10 p-2 rounded-full bg-gray-300 hover:bg-gray-400 transition-all duration-300 ${leftHidden ? 'rotate-180' : ''}`}
          title={leftHidden ? '顯示左側面板' : '隱藏左側面板'}
        >
          {leftHidden ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
        <div className="h-full w-1 bg-gray-300 group-hover:bg-gray-400 transition-colors cursor-col-resize" />
      </div>

      {/* Right panel */}
      <div className={`transition-all duration-300 ${leftHidden ? 'w-full' : 'w-1/2'}`}>
        <div className="h-full flex flex-col">
          <div className="flex items-center justify-between p-3 bg-gray-100 border-b border-gray-300">
            <div className="flex items-center space-x-2">
              <span className="font-medium text-gray-700">新版文件</span>
              <div className="text-xs bg-primary-50 text-primary-700 px-2 py-0.5 rounded">
                修訂版本
              </div>
            </div>
            <div className="flex items-center space-x-2">
              <button
                onClick={handleToggleSync}
                className={`p-2 rounded transition-colors ${syncEnabled ? 'bg-primary-100 text-primary-700' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'}`}
                title={syncEnabled ? '同步滾動啟用' : '同步滾動停用'}
              >
                <div className="flex items-center space-x-1">
                  <div className={`w-2 h-2 rounded-full ${syncEnabled ? 'bg-green-500' : 'bg-gray-400'}`} />
                  <span className="text-xs">{syncEnabled ? '同步中' : '未同步'}</span>
                </div>
              </button>
              {leftHidden && (
                <button
                  onClick={handleToggleLeftPanel}
                  className="p-2 rounded hover:bg-gray-200 transition-colors"
                  title="顯示左側面板"
                >
                  <PanelLeftOpen size={18} />
                </button>
              )}
              <button
                onClick={() => taskId && window.open(`/popout/${taskId}/new`, '_blank', 'width=800,height=900,menubar=no,toolbar=no,location=no')}
                className="p-2 rounded hover:bg-gray-200 transition-colors text-gray-500"
                title="用新視窗彈出 (雙螢幕模式)"
              >
                <ExternalLink size={18} />
              </button>
            </div>
          </div>
          <div
            ref={rightRef}
            className="flex-1 overflow-auto scroll-sync"
          >
            <div className="p-4">
              {rightContent}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SyncScrollContainer;
