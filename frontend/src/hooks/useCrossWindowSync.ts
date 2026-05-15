import { useEffect, useRef, useCallback } from 'react';
import { useCompareStore } from '../stores/compareStore';

const WINDOW_ID = crypto.randomUUID();

export type SyncMessage = 
  | { type: 'SCROLL_SYNC'; payload: { source: 'old' | 'new'; ratio: number; windowId: string } }
  | { type: 'PAGE_CHANGE'; payload: { side: 'old' | 'new'; page: number; windowId: string } }
  | { type: 'DIFF_SELECT'; payload: { diffId: string | null; windowId: string } }
  | { type: 'VIEW_STATE'; payload: { side: 'old' | 'new'; isHidden: boolean; windowId: string } };

export const useCrossWindowSync = (taskId: string | null) => {
  const channelRef = useRef<BroadcastChannel | null>(null);
  
  const { setCurrentPage, setSelectedDiffId, scrollSyncEnabled, getDiffById, openDiffPopup, closeDiffPopup } = useCompareStore();

  const handleMessage = useCallback((event: MessageEvent<SyncMessage>) => {
    const msg = event.data;
    if (msg.payload.windowId === WINDOW_ID) return;

    switch (msg.type) {
      case 'SCROLL_SYNC': {
        if (!scrollSyncEnabled) return;
        // Dispatch custom event that SyncScrollContainer can listen to
        window.dispatchEvent(new CustomEvent('cross-window-scroll', { 
            detail: { source: msg.payload.source, ratio: msg.payload.ratio }
        }));
        break;
      }
      case 'PAGE_CHANGE': {
        // Prevent broadcasting back
        window.dispatchEvent(new CustomEvent('cross-window-page-change', {
            detail: { side: msg.payload.side, page: msg.payload.page }
        }));
        setCurrentPage(msg.payload.side, msg.payload.page);
        break;
      }
      case 'DIFF_SELECT': {
        setSelectedDiffId(msg.payload.diffId);
        if (msg.payload.diffId) {
          document.body.dispatchEvent(new CustomEvent('cross-window-diff-select', { detail: { diffId: msg.payload.diffId } }));
        }
        const diffObj = getDiffById(msg.payload.diffId || '');
        if (diffObj) {
            openDiffPopup(diffObj);
        } else {
            closeDiffPopup();
        }
        break;
      }
      case 'VIEW_STATE': {
         window.dispatchEvent(new CustomEvent('cross-window-view-state', {
            detail: { side: msg.payload.side, isHidden: msg.payload.isHidden }
        }));
        break;
      }
    }
  }, [setCurrentPage, setSelectedDiffId, scrollSyncEnabled, getDiffById, openDiffPopup, closeDiffPopup]);

  useEffect(() => {
    if (!taskId) return;
    
    const channel = new BroadcastChannel(`pdf-sync-${taskId}`);
    channelRef.current = channel;
    channel.addEventListener('message', handleMessage);
    
    return () => {
      channel.removeEventListener('message', handleMessage);
      channel.close();
    };
  }, [taskId, handleMessage]);

  const broadcastScroll = useCallback((source: 'old' | 'new', ratio: number) => {
    channelRef.current?.postMessage({
      type: 'SCROLL_SYNC',
      payload: { source, ratio, windowId: WINDOW_ID }
    } satisfies SyncMessage);
  }, []);

  const broadcastPageChange = useCallback((side: 'old' | 'new', page: number) => {
    channelRef.current?.postMessage({
      type: 'PAGE_CHANGE',
      payload: { side, page, windowId: WINDOW_ID }
    } satisfies SyncMessage);
  }, []);

  const broadcastDiffSelect = useCallback((diffId: string | null) => {
    channelRef.current?.postMessage({
      type: 'DIFF_SELECT',
      payload: { diffId, windowId: WINDOW_ID }
    } satisfies SyncMessage);
  }, []);
  
  const broadcastViewState = useCallback((side: 'old' | 'new', isHidden: boolean) => {
    channelRef.current?.postMessage({
      type: 'VIEW_STATE',
      payload: { side, isHidden, windowId: WINDOW_ID }
    } satisfies SyncMessage);
  }, []);

  return {
    broadcastScroll,
    broadcastPageChange,
    broadcastDiffSelect,
    broadcastViewState
  };
};
