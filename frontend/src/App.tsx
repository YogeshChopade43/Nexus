import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Layout } from './components/layout'
import { ErrorBoundary } from './components/layout/ErrorBoundary'
import { ChatArea } from './components/chat'
import { ChatProvider } from './hooks/useChatContext'

// Pages other than chat load on first visit, keeping the initial download small.
const MarketplacePage = lazy(() => import('./components/marketplace/MarketplacePage').then(m => ({ default: m.MarketplacePage })))
const WorkflowPage = lazy(() => import('./components/workflow').then(m => ({ default: m.WorkflowPage })))
const ActivityPage = lazy(() => import('./components/activity').then(m => ({ default: m.ActivityPage })))
const DashboardPage = lazy(() => import('./components/dashboard/DashboardPage').then(m => ({ default: m.DashboardPage })))
const KnowledgePage = lazy(() => import('./components/knowledge/KnowledgePage').then(m => ({ default: m.KnowledgePage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })))

function App() {
  const location = useLocation()
  return (
    <ChatProvider>
      <Layout>
        {/* Keyed by path so navigating away from a crashed page recovers. */}
        <ErrorBoundary key={location.pathname}>
          <Suspense fallback={<p className="text-sm text-nexus-text-muted">Loading…</p>}>
            <Routes>
              <Route path="/" element={<ChatArea />} />
              <Route path="/servers" element={<MarketplacePage />} />
              <Route path="/apps" element={<Navigate to="/servers" replace />} />
              <Route path="/workflows" element={<WorkflowPage />} />
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/knowledge" element={<KnowledgePage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </Layout>
    </ChatProvider>
  )
}

export default App
