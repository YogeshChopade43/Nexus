import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout'
import { ChatArea } from './components/chat'
import { AppsPage } from './components/apps'
import { WorkflowPage } from './components/workflow'
import { ActivityPage } from './components/activity'
import { SettingsPage } from './pages/SettingsPage'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<ChatArea />} />
        <Route path="/apps" element={<AppsPage />} />
        <Route path="/workflows" element={<WorkflowPage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

export default App