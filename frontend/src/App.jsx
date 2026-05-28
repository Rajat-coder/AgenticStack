import React, { useState, useEffect, useCallback, useRef } from 'react'
import Dashboard from './components/Dashboard'
import Settings from './components/Settings'
import FineTuning from './components/FineTuning'

const API = 'http://localhost:8000'
const WS  = 'ws://localhost:8000/ws'

export default function App() {
  const [tab, setTab]       = useState('dashboard')
  const [jobs, setJobs]     = useState([])
  const [wsStatus, setWs]   = useState('connecting')
  const wsRef               = useRef(null)

  // ── Load all agent jobs ────────────────────────────────────────
  const loadJobs = useCallback(async () => {
    try {
      const res  = await fetch(`${API}/agent/jobs`)
      const data = await res.json()
      setJobs(data)
    } catch (e) {
      console.error('loadJobs failed:', e)
    }
  }, [])

  useEffect(() => { loadJobs() }, [loadJobs])

  // ── WebSocket — server pushes status changes in real time ─────
  // When the harness transitions a job's state, it broadcasts a
  // message here. We update that job in our local state immediately
  // (so the badge flips without waiting for a poll).
  // When status reaches AWAITING_APPROVAL or COMPLETED we also do a
  // full reload so the plan / pr_url data is fresh.
  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(WS)
      wsRef.current = ws

      ws.onopen    = () => setWs('connected')
      ws.onclose   = () => {
        setWs('disconnected')
        setTimeout(connect, 3000)   // auto-reconnect after 3s
      }
      ws.onerror   = () => setWs('error')
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data)
        // Flip the status badge immediately — no full reload needed
        setJobs(prev => prev.map(j =>
          j.job_id === msg.job_id ? { ...j, status: msg.status } : j
        ))
        // Full reload when plan or PR data is newly available
        if (['AWAITING_APPROVAL', 'COMPLETED', 'FAILED', 'TIMED_OUT'].includes(msg.status)) {
          loadJobs()
        }
      }
    }
    connect()
    return () => wsRef.current?.close()
  }, [loadJobs])

  return (
    <div className="app">
      {/* ── Top nav bar ──────────────────────────────────────── */}
      <header className="header">
        <div className="header-brand">
          <span className="header-logo">⚡</span>
          <span className="header-title">AgenticTask</span>
        </div>
        <nav className="header-nav">
          {['dashboard','settings','finetuning'].map(t => (
            <button
              key={t}
              className={`nav-btn ${tab === t ? 'active' : ''}`}
              onClick={() => setTab(t)}
            >
              { t === 'dashboard'  ? 'Dashboard'
              : t === 'settings'   ? 'Settings'
              :                      'Fine-Tuning' }
            </button>
          ))}
        </nav>
        {/* Live / disconnected indicator */}
        <div className={`ws-indicator ${wsStatus}`}>
          <span className="ws-dot" />
          { wsStatus === 'connected' ? 'Live'
          : wsStatus === 'connecting' ? 'Connecting…'
          : 'Disconnected' }
        </div>
      </header>

      {/* ── Page content ─────────────────────────────────────── */}
      <main className="main">
        {tab === 'dashboard'  && <Dashboard jobs={jobs} onRefresh={loadJobs} />}
        {tab === 'settings'   && <Settings />}
        {tab === 'finetuning' && <FineTuning jobs={jobs} onRefresh={loadJobs} />}
      </main>
    </div>
  )
}
