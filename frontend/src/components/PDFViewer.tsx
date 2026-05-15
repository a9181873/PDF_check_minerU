import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { Loader2, ZoomIn, ZoomOut, RotateCw } from 'lucide-react';
import DiffOverlay from './DiffOverlay';
import { DiffItem } from '../services/types';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).toString();

interface PDFViewerProps {
  file: string | File | null;
  currentPage: number;
  onPageChange?: (page: number) => void;
  scale?: number;
  onScaleChange?: (scale: number) => void;
  rotation?: number;
  onRotationChange?: (rotation: number) => void;
  grayscale?: boolean;
  onGrayscaleChange?: (enabled: boolean) => void;
  className?: string;
  showControls?: boolean;
  /** Diff items to overlay on each page */
  diffItems?: DiffItem[];
  /** Expected ID of the currently selected diff */
  selectedDiffId?: string | null;
  /** Callback when a diff overlay rectangle is clicked */
  onDiffClick?: (diff: DiffItem) => void;
  /** Whether to show the text label inside each diff overlay */
  showDiffLabels?: boolean;
}

/** Track per-page original PDF dimensions (in PDF points, scale-independent) */
interface PageDimension {
  pdfWidth: number;
  pdfHeight: number;
}

interface PdfPageProxyLike {
  originalWidth?: number;
  originalHeight?: number;
  width?: number;
  height?: number;
  cleanup?: () => void;
  getViewport: (options: { scale: number; rotation?: number }) => { width: number; height: number };
}

interface PdfDocumentProxyLike {
  numPages: number;
  getPage: (pageNumber: number) => Promise<PdfPageProxyLike>;
}

const DEFAULT_PAGE_WIDTH = 595;
const DEFAULT_PAGE_HEIGHT = 842;

const PDFViewer: React.FC<PDFViewerProps> = ({
  file,
  currentPage,
  onPageChange,
  scale = 1.0,
  onScaleChange,
  rotation = 0,
  onRotationChange,
  grayscale = false,
  onGrayscaleChange,
  className = '',
  showControls = true,
  diffItems = [],
  selectedDiffId = null,
  onDiffClick,
  showDiffLabels = true,
}) => {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pageDimensions, setPageDimensions] = useState<Map<number, PageDimension>>(new Map());
  const [visiblePages, setVisiblePages] = useState<Set<number>>(new Set([currentPage]));
  const pageContainerRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const observerRef = useRef<IntersectionObserver | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const loadSeqRef = useRef(0);

  const documentKey =
    typeof file === 'string'
      ? file
      : file
        ? `${file.name}-${file.lastModified}-${file.size}`
        : 'empty';

  const selectedDiffPage = useMemo(() => {
    if (!selectedDiffId) return null;
    const diff = diffItems.find((item) => item.id === selectedDiffId);
    return diff?.new_bbox?.page ?? diff?.old_bbox?.page ?? null;
  }, [diffItems, selectedDiffId]);

  const includePageWindow = useCallback((source: Set<number>, page: number, totalPages: number | null) => {
    const next = new Set(source);
    const maxPage = totalPages ?? page;
    for (let p = Math.max(1, page - 1); p <= Math.min(maxPage, page + 1); p += 1) {
      next.add(p);
    }
    return next;
  }, []);

  useEffect(() => {
    loadSeqRef.current += 1;
    const resetTimer = window.setTimeout(() => {
      setNumPages(null);
      setError(null);
      setPageDimensions(new Map());
      setVisiblePages(new Set([1]));
      setIsLoading(Boolean(file));
    }, 0);

    return () => window.clearTimeout(resetTimer);
  }, [documentKey, file]);

  useEffect(() => {
    if (selectedDiffId && viewerRef.current) {
      // Allow a small delay to ensure DOM is updated and DiffOverlay is rendered
      const timer = setTimeout(() => {
        if (!viewerRef.current) return;
        const selectedEl = viewerRef.current.querySelector('.is-selected');
        if (selectedEl) {
          selectedEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [selectedDiffId, numPages]);

  useEffect(() => () => {
    loadSeqRef.current += 1;
    observerRef.current?.disconnect();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setVisiblePages((prev) => includePageWindow(prev, currentPage, numPages));
      if (selectedDiffPage === currentPage) {
        return;
      }
      const pageEl = pageContainerRefs.current.get(currentPage);
      pageEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 80);

    return () => window.clearTimeout(timer);
  }, [currentPage, includePageWindow, numPages, selectedDiffPage]);

  useEffect(() => {
    observerRef.current?.disconnect();

    if (!numPages || !scrollerRef.current) {
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        setVisiblePages((prev) => {
          const next = new Set(prev);
          entries.forEach((entry) => {
            const page = Number((entry.target as HTMLElement).dataset.page);
            if (!page) {
              return;
            }

            if (entry.isIntersecting) {
              next.add(page);
            } else if (Math.abs(page - currentPage) > 1) {
              next.delete(page);
            }
          });

          return includePageWindow(next, currentPage, numPages);
        });
      },
      {
        root: scrollerRef.current,
        rootMargin: '1200px 0px',
        threshold: 0.01,
      }
    );

    observerRef.current = observer;
    pageContainerRefs.current.forEach((el) => observer.observe(el));

    return () => {
      observer.disconnect();
      if (observerRef.current === observer) {
        observerRef.current = null;
      }
    };
  }, [currentPage, includePageWindow, numPages]);

  const handleDocumentLoadSuccess = async (pdf: PdfDocumentProxyLike) => {
    const sequence = loadSeqRef.current;
    const totalPages = pdf.numPages;
    setNumPages(totalPages);
    setIsLoading(false);
    setError(null);
    setVisiblePages((prev) => includePageWindow(prev, currentPage, totalPages));

    const dimensions = new Map<number, PageDimension>();
    try {
      for (let pageNum = 1; pageNum <= totalPages; pageNum += 1) {
        if (sequence !== loadSeqRef.current) {
          return;
        }
        const page = await pdf.getPage(pageNum);
        const viewport = page.getViewport({ scale: 1, rotation: 0 });
        dimensions.set(pageNum, {
          pdfWidth: viewport.width,
          pdfHeight: viewport.height,
        });
        page.cleanup?.();
      }

      if (sequence === loadSeqRef.current) {
        setPageDimensions(dimensions);
      }
    } catch (dimensionError) {
      console.error('PDF page dimension load error:', dimensionError);
    }
  };

  const handleDocumentLoadError = (loadError: Error) => {
    const sequence = loadSeqRef.current;
    window.setTimeout(() => {
      if (sequence !== loadSeqRef.current) {
        return;
      }
      setIsLoading(false);
      setError(`無法載入 PDF: ${loadError.message}`);
    }, 0);
    console.error('PDF load error:', loadError);
  };

  /**
   * react-pdf Page onLoadSuccess gives us the page proxy with
   * originalWidth / originalHeight (PDF points) and width / height (rendered px).
   * This is the most precise way to get coordinate mapping.
   */
  const handlePageLoadSuccess = useCallback((pageNum: number, page: PdfPageProxyLike) => {
    const sequence = loadSeqRef.current;
    // Only store scale-independent PDF point dimensions.
    // Rendered pixel size is not stored — the overlay uses % positioning instead.
    const pdfWidth = page.originalWidth ?? (page.width ?? DEFAULT_PAGE_WIDTH * scale) / scale;
    const pdfHeight = page.originalHeight ?? (page.height ?? DEFAULT_PAGE_HEIGHT * scale) / scale;

    setPageDimensions((prev) => {
      if (sequence !== loadSeqRef.current) {
        return prev;
      }
      const current = prev.get(pageNum);
      if (current?.pdfWidth === pdfWidth && current?.pdfHeight === pdfHeight) {
        return prev;
      }
      const next = new Map(prev);
      next.set(pageNum, { pdfWidth, pdfHeight });
      return next;
    });
  }, [scale]);

  const setPageContainerRef = useCallback((pageNum: number, el: HTMLDivElement | null) => {
    if (el) {
      pageContainerRefs.current.set(pageNum, el);
      observerRef.current?.observe(el);
    } else {
      const existing = pageContainerRefs.current.get(pageNum);
      if (existing) {
        observerRef.current?.unobserve(existing);
        pageContainerRefs.current.delete(pageNum);
      }
    }
  }, []);

  const handleZoomIn = () => {
    const newScale = Math.min(scale + 0.25, 3.0);
    onScaleChange?.(newScale);
  };

  const handleZoomOut = () => {
    const newScale = Math.max(scale - 0.25, 0.5);
    onScaleChange?.(newScale);
  };

  const handleRotate = () => {
    const newRotation = (rotation + 90) % 360;
    onRotationChange?.(newRotation);
  };

  const handlePreviousPage = () => {
    if (currentPage > 1) {
      onPageChange?.(currentPage - 1);
    }
  };

  const handleNextPage = () => {
    if (numPages && currentPage < numPages) {
      onPageChange?.(currentPage + 1);
    }
  };

  const handlePageInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const page = parseInt(e.target.value, 10);
    if (!isNaN(page) && page >= 1 && page <= (numPages || 1)) {
      onPageChange?.(page);
    }
  };

  return (
    <div ref={viewerRef} className={`flex flex-col h-full ${className}`}>
      {showControls && (
        <div className="flex items-center justify-between p-3 bg-gray-100 border-b border-gray-300 rounded-t-lg">
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2">
              <button
                onClick={handlePreviousPage}
                disabled={currentPage <= 1}
                className="p-2 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="上一頁"
              >
                ←
              </button>
              <div className="flex items-center space-x-2">
                <input
                  type="number"
                  min="1"
                  max={numPages || 1}
                  value={currentPage}
                  onChange={handlePageInputChange}
                  className="w-16 px-2 py-1 text-center border border-gray-300 rounded"
                />
                <span className="text-gray-600">/ {numPages || '-'}</span>
              </div>
              <button
                onClick={handleNextPage}
                disabled={!numPages || currentPage >= numPages}
                className="p-2 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="下一頁"
              >
                →
              </button>
            </div>
          </div>

          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2">
              <button
                onClick={handleZoomOut}
                disabled={scale <= 0.5}
                className="p-2 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="縮小"
              >
                <ZoomOut size={18} />
              </button>
              <span className="text-sm font-medium">{Math.round(scale * 100)}%</span>
              <button
                onClick={handleZoomIn}
                disabled={scale >= 3.0}
                className="p-2 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="放大"
              >
                <ZoomIn size={18} />
              </button>
            </div>

            <button
              onClick={handleRotate}
              className="p-2 rounded hover:bg-gray-200 transition-colors"
              title="旋轉"
            >
              <RotateCw size={18} />
            </button>

            <div className="flex items-center space-x-2">
              <span className="text-sm text-gray-600">灰階</span>
              <button
                type="button"
                onClick={() => onGrayscaleChange?.(!grayscale)}
                disabled={!onGrayscaleChange}
                className={`w-12 h-6 flex items-center rounded-full p-1 transition-colors ${
                  grayscale ? 'bg-primary-600' : 'bg-gray-300'
                } ${onGrayscaleChange ? 'cursor-pointer' : 'cursor-default'}`}
              >
                <div className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${grayscale ? 'translate-x-6' : ''}`} />
              </button>
            </div>
          </div>
        </div>
      )}

      <div
        ref={scrollerRef}
        data-pdf-scroller="true"
        className="relative flex-1 bg-gray-200 rounded-b-lg overflow-auto"
      >
        {file ? (
          <>
            {isLoading && (
              <div className="absolute inset-0 flex items-center justify-center z-10">
                <div className="text-center">
                  <Loader2 className="w-8 h-8 animate-spin text-primary-600 mx-auto mb-3" />
                  <p className="text-gray-600">載入 PDF 中...</p>
                </div>
              </div>
            )}

            {error && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center p-6 bg-red-50 rounded-lg max-w-md">
                  <p className="text-red-700 font-medium mb-2">載入失敗</p>
                  <p className="text-red-600 text-sm">{error}</p>
                </div>
              </div>
            )}

            {!error && (
              <Document
                key={documentKey}
                file={file}
                onLoadSuccess={handleDocumentLoadSuccess}
                onLoadError={handleDocumentLoadError}
                loading={null}
              >
                <div>
                  {numPages && Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => {
                    const dims = pageDimensions.get(pageNum);
                    const isRotatedSideways = Math.abs(rotation % 180) === 90;
                    const pdfWidth = dims?.pdfWidth ?? DEFAULT_PAGE_WIDTH;
                    const pdfHeight = dims?.pdfHeight ?? DEFAULT_PAGE_HEIGHT;
                    const pageWidth = (isRotatedSideways ? pdfHeight : pdfWidth) * scale;
                    const pageHeight = (isRotatedSideways ? pdfWidth : pdfHeight) * scale;
                    const shouldRenderPage = visiblePages.has(pageNum);

                    return (
                      <div
                        key={pageNum}
                        ref={(el) => setPageContainerRef(pageNum, el)}
                        data-page={pageNum}
                        className="flex justify-center py-3"
                        style={{ minHeight: pageHeight + 24 }}
                      >
                        {/* Page + overlay wrapper: relative so overlay is scoped to this page */}
                        <div
                          className="relative inline-block"
                          style={{ verticalAlign: 'top', width: pageWidth, minHeight: pageHeight }}
                        >
                          {shouldRenderPage ? (
                            <>
                              {/* Grayscale applied only to PDF canvas, NOT the diff overlay */}
                              <div className={grayscale ? 'filter-grayscale' : ''}>
                                <Page
                                  pageNumber={pageNum}
                                  scale={scale}
                                  rotate={rotation}
                                  renderTextLayer={false}
                                  renderAnnotationLayer={false}
                                  className="pdf-page shadow-md"
                                  onLoadSuccess={(page) => handlePageLoadSuccess(pageNum, page)}
                                />
                              </div>
                            </>
                          ) : (
                            <div
                              aria-hidden="true"
                              className="flex items-center justify-center rounded bg-white/70 shadow-sm"
                              style={{ width: pageWidth, height: pageHeight }}
                            >
                              <span className="text-xs text-gray-400">{pageNum} / {numPages}</span>
                            </div>
                          )}
                          {/* Per-page diff overlay — outside grayscale wrapper so colors stay vivid */}
                          {shouldRenderPage && dims && diffItems.length > 0 && (
                            <DiffOverlay
                              diffItems={diffItems}
                              selectedDiffId={selectedDiffId}
                              pageNumber={pageNum}
                              pdfPageWidth={dims.pdfWidth}
                              pdfPageHeight={dims.pdfHeight}
                              onDiffClick={onDiffClick}
                              showLabels={showDiffLabels}
                            />
                          )}
                          {/* Page number badge */}
                          {shouldRenderPage ? (
                            <div className="absolute top-3 right-3 bg-black/50 text-white text-xs px-2 py-0.5 rounded-full z-10">
                              {pageNum} / {numPages}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Document>
            )}
          </>
        ) : !error ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center p-8">
              <div className="w-16 h-16 mx-auto mb-4 bg-gray-300 rounded-full flex items-center justify-center">
                <span className="text-gray-500 text-2xl">PDF</span>
              </div>
              <p className="text-gray-600">未選擇 PDF 檔案</p>
              <p className="text-gray-500 text-sm mt-1">請上傳檔案以預覽</p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default PDFViewer;
