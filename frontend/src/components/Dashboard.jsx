import React, { useState, useEffect, useCallback } from 'react'
import StatusBadge from './StatusBadge'
import AgentPanel  from './AgentPanel'

const API = 'http://localhost:8000'

// ── Time helper ────────────────────────────────────────────────
function timeAgo(dateStr) {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1)  return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ──────────────────────────────────────────────────────────────
// Dashboard — the main page
//
// Layout (3 columns when a job is selected, 2 otherwise):
//   Left pane:   JIRA Tickets OR Agent Jobs (tab toggle)
//   Right panel: Agent detail for selected job
//
// Data flow:
//   - jobs come from App.jsx (kept there so WebSocket can update them)
//   - tickets are fetched locally (they don't change via WebSocket)
// ──────────────────────────────────────────────────────────────
export default function Dashboard({ jobs, onRefresh }) {
  const [leftTab,      setLeftTab    ] = useState('tickets')   // 'tickets' | 'jobs'
  const [tickets,      setTickets    ] = useState([])
  const [loadingTix,   setLoadingTix ] = useState(true)
  const [selectedJob,  setSelectedJob] = useState(null)
  const [assigning,    setAssigning  ] = useState({})   // { ticket_id: true } while assigning
  const [tixError,     setTixError   ] = useState('')

  // ── Load JIRA tickets ────────────────────────────────────────
  const loadTickets = useCallback(async () => {
    setLoadingTix(true); setTixError('')
    try {
      const res = await fetch(`${API}/tickets`)
      if (!res.ok) throw new Error(`${res.status}`)
      setTickets(await res.json())
    } catch (e) {
      setTixError(`Could not load tickets: ${e.message}`)
    } finally {
      setLoadingTix(false)
    }
  }, [])

  useEffect(() => { loadTickets() }, [loadTickets])

  // Keep selectedJob in sync when jobs list refreshes
  useEffect(() => {
    if (!selectedJob) return
    const fresh = jobs.find(j => j.job_id === selectedJob.job_id)
    if (fresh) setSelectedJob(fresh)
  }, [jobs])

  // ── Assign ticket to agent ───────────────────────────────────
  const handleAssign = async (ticket) => {
    setAssigning(p => ({ ...p, [ticket.ticket_id]: true }))
    try {
      const res = await fetch(`${API}/agent/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticket_id: ticket.ticket_id, ticket_title: ticket.title }),
      })
      if (!res.ok) {
        const d = await res.json()
        alert(d.detail ?? 'Assign failed')
      } else {
        const newJob = await res.json()
        await onRefresh()                       // reload jobs list
        setLeftTab('jobs')                      // switch to jobs tab automatically
        // Select the new job in the panel
        setTimeout(() => {
          setSelectedJob(jobs.find(j => j.job_id === newJob.job_id) ?? {
            job_id:       newJob.job_id,
            ticket_id:    ticket.ticket_id,
            ticket_title: ticket.title,
            status:       newJob.status,
            plan:         null,
            branch_name:  null,
            pr_url:       null,
          })
        }, 100)
      }
    } catch (e) {
      alert('Network error')
    } finally {
      setAssigning(p => ({ ...p, [ticket.ticket_id]: false }))
    }
  }

  // ── Detect if a ticket already has an active job ─────────────
  const activeStatuses = new Set([
    'QUEUED','GATHERING_CONTEXT','PLANNING','AWAITING_APPROVAL','EXECUTING','RAISING_PR'
  ])
  const activeJobsByTicket = {}
  for (const j of jobs) {
    if (activeStatuses.has(j.status)) activeJobsByTicket[j.ticket_id] = j
  }

  const hasPanel = !!selectedJob

  return (
    <div className={`dashboard ${hasPanel ? 'with-panel' : ''}`}>

      {/* ══ Left pane: Tickets / Jobs toggle ══════════════════ */}
      <div className="pane">
        <div className="pane-header">
          <div className="pane-tabs">
            <button
              className={`pane-tab ${leftTab === 'tickets' ? 'active' : ''}`}
              onClick={() => setLeftTab('tickets')}
            >
              Tickets
            </button>
            <button
              className={`pane-tab ${leftTab === 'jobs' ? 'active' : ''}`}
              onClick={() => setLeftTab('jobs')}
            >
              Jobs {jobs.length > 0 && `(${jobs.length})`}
            </button>
          </div>
        </div>

        <div className="pane-body">
          {/* ── JIRA Tickets tab ──────────────────────────── */}
          {leftTab === 'tickets' && (
            <>
              {tixError && <div className="error-msg">{tixError}</div>}
              {loadingTix && <div className="loading">Loading tickets…</div>}
              {!loadingTix && tickets.length === 0 && !tixError && (
                <div className="loading">No tickets found in JIRA project.</div>
              )}
              {tickets.map(t => {
                const existing = activeJobsByTicket[t.ticket_id]
                return (
                  <div
                    key={t.ticket_id}
                    className="ticket-card"
                    onClick={() => {
                      if (existing) {
                        setSelectedJob(existing)
                        setLeftTab('jobs')
                      }
                    }}
                  >
                    <div className="ticket-id">{t.ticket_id}</div>
                    <div className="ticket-title">{t.title}</div>
                    <div className="ticket-meta">
                      <span className="ticket-status-pill">{t.status}</span>
                      {existing ? (
                        // Already has an active job — show its current status
                        <StatusBadge status={existing.status} />
                      ) : (
                        <button
                          className="assign-btn"
                          disabled={!!assigning[t.ticket_id]}
                          onClick={e => { e.stopPropagation(); handleAssign(t) }}
                        >
                          {assigning[t.ticket_id] ? '…' : 'Assign to Agent'}
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </>
          )}

          {/* ── Agent Jobs tab ────────────────────────────── */}
          {leftTab === 'jobs' && (
            <>
              {jobs.length === 0 && (
                <div className="loading">No jobs yet. Assign a ticket to get started.</div>
              )}
              {jobs.map(j => (
                <div
                  key={j.job_id}
                  className={`job-card ${selectedJob?.job_id === j.job_id ? 'selected' : ''} ${j.status === 'AWAITING_APPROVAL' ? 'needs-action' : ''}`}
                  onClick={() => setSelectedJob(j)}
                >
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--primary)' }}>{j.ticket_id}</div>
                  <div className="job-title">{j.ticket_title}</div>
                  <div className="job-meta">
                    <StatusBadge status={j.status} />
                    {j.status === 'AWAITING_APPROVAL' && (
                      <span style={{ fontSize: 11, color: 'var(--warning)' }}>⚠ Needs approval</span>
                    )}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* ══ Middle pane (only when panel is open) ════════════ */}
      {hasPanel && (
        <div className="pane">
          <div className="pane-header">
            <div className="pane-title">All Jobs</div>
            <div className="pane-subtitle">{jobs.length} total</div>
          </div>
          <div className="pane-body">
            {jobs.map(j => (
              <div
                key={j.job_id}
                className={`job-card ${selectedJob?.job_id === j.job_id ? 'selected' : ''} ${j.status === 'AWAITING_APPROVAL' ? 'needs-action' : ''}`}
                onClick={() => setSelectedJob(j)}
              >
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--primary)' }}>{j.ticket_id}</div>
                <div className="job-title">{j.ticket_title}</div>
                <div className="job-meta">
                  <StatusBadge status={j.status} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ══ Right panel: job detail ════════════════════════════ */}
      <AgentPanel
        job={selectedJob}
        onRefresh={async () => {
          await onRefresh()
          // refresh selectedJob after reload
          if (selectedJob) {
            const fresh = jobs.find(j => j.job_id === selectedJob.job_id)
            if (fresh) setSelectedJob(fresh)
          }
        }}
      />
    </div>
  )
}
