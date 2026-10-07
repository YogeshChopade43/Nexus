import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Layout } from './components/layout'
import { ErrorBoundary } from './components/layout/ErrorBoundary'
import { ChatArea } from './components/chat'
import { ServersPage } from './components/servers/ServersPage'
import { WorkflowPage } from './components/workflow'
import { ActivityPage } from './components/activity'
import { SettingsPage } from './pages/SettingsPage'
import { ChatProvider } from './hooks/useChatContext'

function App() {
  const location = useLocation()
  return (
    <ChatProvider>
      <Layout>
        {/* Keyed by path so navigating away from a crashed page recovers. */}
        <ErrorBoundary key={location.pathname}>
          <Routes>
            <Route path="/" element={<ChatArea />} />
            <Route path="/servers" element={<ServersPage />} />
            <Route path="/apps" element={<Navigate to="/servers" replace />} />
            <Route path="/workflows" element={<WorkflowPage />} />
            <Route path="/activity" element={<ActivityPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
      </Layout>
    </ChatProvider>
  )
}

export default App
