import { Suspense, lazy, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './stores/authStore';

const LoginPage = lazy(() => import('./pages/LoginPage'));
const UploadPage = lazy(() => import('./pages/UploadPage'));
const ComparePage = lazy(() => import('./pages/ComparePage'));
const PopoutPage = lazy(() => import('./pages/PopoutPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));

function RouteFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[linear-gradient(180deg,_#f5f5f5_0%,_#eef4ef_100%)]">
      <div className="text-center">
        <div className="w-12 h-12 mx-auto mb-4 border-4 border-primary-600 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm tracking-[0.18em] uppercase text-primary-700">Loading workspace</p>
      </div>
    </div>
  );
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function App() {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage);

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedRoute><UploadPage /></ProtectedRoute>} />
          <Route path="/compare/:taskId" element={<ProtectedRoute><ComparePage /></ProtectedRoute>} />
          <Route path="/popout/:taskId/:version" element={<ProtectedRoute><PopoutPage /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute><AdminPage /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
