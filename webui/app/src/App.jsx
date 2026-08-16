import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Workers from './pages/Workers'
import WorkerDetail from './pages/WorkerDetail'
import Devices from './pages/Devices'
import Agents from './pages/Agents'
import AgentLuns from './pages/AgentLuns'
import Operations from './pages/Operations'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="workers" element={<Workers />} />
        <Route path="workers/:id" element={<WorkerDetail />} />
        <Route path="devices" element={<Devices />} />
        <Route path="agents" element={<Agents />} />
        <Route path="agents/:id" element={<AgentLuns />} />
        <Route path="operations" element={<Operations />} />
      </Route>
    </Routes>
  )
}
