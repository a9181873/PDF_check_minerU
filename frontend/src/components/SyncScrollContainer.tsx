import React, { useCallback, useEffect, useRef } from 'react';
import { PanelLeftClose, PanelLeftOpen, ExternalLink } from 'lucide-react';

interface SyncScrollContainerProps {
  leftContent: React.ReactNode;
  rightContent: React.ReactNode;
  syncEnabled?: boolean;
  onSyncToggle?: (enabled: boolean) => void;
  onScrollSync?: (source: 'old' | 'new', ratio: number) => void;
  leftHidden?: boolean;
  onLeftHiddenToggle?: (hidden: boolean) => void;
  taskId?: string;
  className?: string;
}

const PDF_SCROLLER_SELECTOR = '[data-pdf-scroller="true"]';
type PaneSide = 'left' | 'right';

const getScrollElement = (pane: HTMLDivElement | null): HTMLElement | null => {
  if (!pane) return null;
  return pane.querySelector<HTMLElement>(PDF_SCROLLER_SELECTOR) ?? pane;
};

const getScrollableDistance = (el: HTMLElement): number => Math.max(0, el.scrollHeight - el.clientHeight);

const clampRatio = (ratio: number): number => Math.min(1, Math.max(0, ratio));

const SyncScrollContainer: React.FC<SyncScrollContainerProps> = ({
  leftContent,
  rightContent,
  syncEnabled = true,
  onSyncToggle,
  onScrollSync,
  leftHidden = false,
  onLeftHiddenToggle,
  taskId,
  className = '',
}) => {
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const pendingSyncRef = useRef<{ source: PaneSide; ratio: number } | null>(null);
  const programmaticScrollRef = useRef<Record<PaneSide, { top: number; until: number } | null>>({
    left: null,
    right: null,
  });

  const getPaneRef = useCallback((side: PaneSide) => (side === 'left' ? leftRef.current : rightRef.current), []);

  const shouldIgnoreProgrammaticScroll = useCallback((side: PaneSide, el: HTMLElement) => {
    const marker = programmaticScrollRef.current[side];
    if (!marker) return false;

    if (performance.now() > marker.until) {
      programmaticScrollRef.current[side] = null;
      return false;
    }

    if (Math.abs(el.scrollTop - marker.top) <= 2) {
      programmaticScrollRef.current[side] = null;
      return true;
    }

    return false;
  }, []);

  const applyScrollRatio = useCallback((side: PaneSide, ratio: number) => {
    const el = getScrollElement(getPaneRef(side));
    if (!el) return;

    const scrollable = getScrollableDistance(el);
    if (scrollable <= 0) return;

    const targetTop = clampRatio(ratio) * scrollable;
    if (Math.abs(el.scrollTop - targetTop) <= 1) return;

    el.scrollTop = targetTop;
    programmaticScrollRef.current[side] = {
      top: el.scrollTop,
      until: performance.now() + 100,
    };
  }, [getPaneRef]);

  // Sync scroll positions on the next paint. This keeps both panes visually locked
  // during fast wheel/trackpad scrolling without letting programmatic scroll events
  // bounce back and throttle the user's active pane.
  const syncScroll = useCallback((source: PaneSide, sourceScrollEl?: HTMLElement) => {
    if (!syncEnabled) return;

    const sourceEl = sourceScrollEl ?? getScrollElement(getPaneRef(source));
    if (!sourceEl) return;

    const sourceScrollable = getScrollableDistance(sourceEl);
    if (sourceScrollable <= 0) return;

    pendingSyncRef.current = {
      source,
      ratio: clampRatio(sourceEl.scrollTop / sourceScrollable),
    };

    if (rafRef.current !== null) return;

    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = null;

      const pending = pendingSyncRef.current;
      pendingSyncRef.current = null;
      if (!pending) return;

      const target: PaneSide = pending.source === 'left' ? 'right' : 'left';
      applyScrollRatio(target, pending.ratio);
      onScrollSync?.(pending.source === 'left' ? 'old' : 'new', pending.ratio);
    });
  }, [applyScrollRatio, getPaneRef, onScrollSync, syncEnabled]);

  useEffect(() => {
    const leftEl = leftRef.current;
    const rightEl = rightRef.current;
    
    const handleLeftScroll = (event: Event) => {
      const el = event.target as HTMLElement;
      if (shouldIgnoreProgrammaticScroll('left', el)) return;
      syncScroll('left', el);
    };
    const handleRightScroll = (event: Event) => {
      const el = event.target as HTMLElement;
      if (shouldIgnoreProgrammaticScroll('right', el)) return;
      syncScroll('right', el);
    };
    
    if (leftEl) {
      leftEl.addEventListener('scroll', handleLeftScroll, true);
    }
    
    if (rightEl) {
      rightEl.addEventListener('scroll', handleRightScroll, true);
    }
    
    return () => {
      if (leftEl) {
        leftEl.removeEventListener('scroll', handleLeftScroll, true);
      }
      if (rightEl) {
        rightEl.removeEventListener('scroll', handleRightScroll, true);
      }
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [shouldIgnoreProgrammaticScroll, syncScroll]);

  // Listen for incoming cross-window scroll events
  useEffect(() => {
    const handleCrossWindowScroll = (e: Event) => {
      const customEvent = e as CustomEvent<{ source: 'old' | 'new', ratio: number }>;
      const { ratio } = customEvent.detail;

      applyScrollRatio('left', ratio);
      applyScrollRatio('right', ratio);
    };

    window.addEventListener('cross-window-scroll', handleCrossWindowScroll);
    return () => window.removeEventListener('cross-window-scroll', handleCrossWindowScroll);
  }, [applyScrollRatio]);

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
            className="flex-1 overflow-hidden scroll-sync"
          >
            <div className="p-4 h-full">
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
            className="flex-1 overflow-hidden scroll-sync"
          >
            <div className="p-4 h-full">
              {rightContent}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SyncScrollContainer;
