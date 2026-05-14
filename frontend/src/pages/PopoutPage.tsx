import React, { Suspense, lazy, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useCompareStore } from '../stores/compareStore';
import { compareApi, buildAuthedUrl } from '../services/api';
import { useCrossWindowSync } from '../hooks/useCrossWindowSync';

const PDFViewer = lazy(() => import('../components/PDFViewer'));

function InlineLoader({ label }: { label: string }) {
  return (
    <div className="flex h-screen items-center justify-center bg-[linear-gradient(180deg,_rgba(255,255,255,0.96)_0%,_rgba(245,245,245,0.96)_100%)]">
      <div className="text-center">
        <div className="mx-auto mb-4 h-10 w-10 rounded-full border-4 border-primary-600 border-t-transparent animate-spin" />
        <p className="text-sm uppercase tracking-[0.18em] text-primary-700">{label}</p>
      </div>
    </div>
  );
}

const PopoutPage: React.FC = () => {
  const { taskId, version } = useParams<{ taskId: string; version: 'old' | 'new' }>();
  
  const {
    report,
    setTaskId,
    setReport,
    filteredItems,
    currentPage,
    setCurrentPage,
    openDiffPopup,
    scale,
    setScale,
    grayscaleEnabled,
    setGrayscaleEnabled,
  } = useCompareStore();

  const [isLoading, setIsLoading] = useState(true);
  const { broadcastScroll, broadcastPageChange, broadcastDiffSelect } = useCrossWindowSync(taskId || null);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const isSyncingRef = React.useRef(false);

  useEffect(() => {
    if (taskId) {
      setTaskId(taskId);
      
      const loadComparison = async () => {
        try {
          const reportData = await compareApi.getResult(taskId);
          setReport(reportData);
        } catch (err) {
          console.error('Failed to load comparison result in popout window', err);
        } finally {
          setIsLoading(false);
        }
      };
      
      void loadComparison();
    }
  }, [taskId, setTaskId, setReport]);

  useEffect(() => {
    // Listen for incoming cross-window scroll events
    const handleScrollEvent = (e: CustomEvent<{ source: string, ratio: number }>) => {
      if (!containerRef.current) return;
      if (e.detail.source === version || e.detail.source === 'popout') return;
      
      isSyncingRef.current = true;
      const targetEl = containerRef.current;
      const targetScrollable = targetEl.scrollHeight - targetEl.clientHeight;
      if (targetScrollable > 0) {
          targetEl.scrollTop = e.detail.ratio * targetScrollable;
      }
      setTimeout(() => { isSyncingRef.current = false; }, 50);
    };

    window.addEventListener('cross-window-scroll', handleScrollEvent as EventListener);
    return () => window.removeEventListener('cross-window-scroll', handleScrollEvent as EventListener);
  }, [version]);

  useEffect(() => {
    // When the custom page-change event is fired by 'useCrossWindowSync' 
    // it already updates `useCompareStore`.
    const handlePageEvent = (e: CustomEvent<{ side: string, page: number }>) => {
        // Nothing explicit needed unless we need local state, but the store handles it
    };
    window.addEventListener('cross-window-page-change', handlePageEvent as EventListener);
    return () => window.removeEventListener('cross-window-page-change', handlePageEvent as EventListener);
  }, []);

  const handleScroll = () => {
    if (isSyncingRef.current || !containerRef.current) return;
    const el = containerRef.current;
    const scrollable = el.scrollHeight - el.clientHeight;
    if (scrollable > 0) {
      const ratio = el.scrollTop / scrollable;
      broadcastScroll(version || 'old', ratio);
    }
  };

  const handlePageChange = (page: number) => {
    const side = version || 'old';
    setCurrentPage(side, page);
    broadcastPageChange(side, page);
  };
  
  const handleDiffClick = (diff: any) => {
     openDiffPopup(diff);
     broadcastDiffSelect(diff.id);
  };

  if (isLoading || !report || !taskId || !version) {
    return <InlineLoader label="Loading document" />;
  }

  const pdfUrl = buildAuthedUrl(`/api/compare/${taskId}/pdf/${version}`);

  return (
    <div className="h-screen w-screen overflow-hidden bg-gray-100 flex flex-col">
       <div className="flex items-center justify-between p-3 bg-gray-100 border-b border-gray-300 shadow-sm z-10">
            <div className="flex items-center space-x-2">
              <span className="font-medium text-gray-700">
                  {version === 'old' ? '舊版文件' : '新版文件'}
              </span>
              <div className={`text-xs px-2 py-0.5 rounded ${version === 'old' ? 'bg-gray-300 text-gray-700' : 'bg-primary-50 text-primary-700'}`}>
                {version === 'old' ? '原始版本' : '修訂版本'}
              </div>
            </div>
        </div>
        <div 
           ref={containerRef}
           onScroll={handleScroll}
           className="flex-1 overflow-auto w-full relative" style={{ scrollBehavior: 'smooth' }}
        >
          <div className="p-4 w-full h-full pb-32">
            <Suspense fallback={<InlineLoader label="Loading PDF" />}>
              <PDFViewer
                  file={pdfUrl}
                  currentPage={currentPage[version]}
                  onPageChange={handlePageChange}
                  scale={scale}
                  onScaleChange={setScale}
                  grayscale={grayscaleEnabled}
                  onGrayscaleChange={setGrayscaleEnabled}
                  showControls={true}
                  diffItems={filteredItems}
                  onDiffClick={handleDiffClick}
              />
            </Suspense>
          </div>
        </div>
    </div>
  );
};

export default PopoutPage;
