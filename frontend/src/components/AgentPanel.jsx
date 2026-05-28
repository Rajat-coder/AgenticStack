import React, { useState } from 'react'
import StatusBadge from './StatusBadge'

const API = 'http://localhost:8000'

// ── Small helper: time since a date string ─────────────────────
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
// AgentPanel — full detail view for one agent job
//
// Shown when user clicks a job in the jobs list.
// Responsibilities:
//  - Display status + plan (summary, files, steps, questions)
//  - Approve button → POST /agent/approve/{job_id}
//  - Revise button → shows feedback textarea → POST /agent/revise/{job_id}
//  - Stop button → POST /agent/stop/{job_id}
// ──────────────────────────────────────────────────────────────
export default function AgentPanel({ job, onRefresh }) {
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedback,     setFeedback    ] = useState('')
  const [loading,      setLoading     ] = useState(false)
  const [error,        setError       ] = useState('')

  if (!job) {
    return (
      <div className="agent-panel">
        <div className="empty-panel">
          <div className="empty-icon">🤖</div>
          <div className="empty-text">No job selected</div>
          <div className="empty-hint">Click a job from the list to see details</div>
        </div>
      </div>
    )
  }

  const plan     = job.plan   // null until AWAITING_APPROVAL
  const isWaiting = job.status === 'AWAITING_APPROVAL'
  const isActive  = ['QUEUED','GATHERING_CONTEXT','PLANNING','EXECUTING','RAISING_PR'].includes(job.status)
  const isDone    = ['COMPLETED','FAILED','TIMED_OUT'].includes(job.status)

  // ── Approve plan ─────────────────────────────────────────────
  const handleApprove = async () => {
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/agent/approve/${job.job_id}`, { method: 'POST' })
      if (!res.ok) {
        const d = await res.json()
        setError(d.detail ?? 'Approve failed')
      } else {
        onRefresh()
      }
    } catch (e) {
      setError('Network error')
    } finally {
      setLoading(false)
    }
  }

  // ── Submit revision feedback ──────────────────────────────────
  const handleRevise = async () => {
    if (!feedback.trim()) return
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/agent/revise/${job.job_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback }),
      })
      if (!res.ok) {
        const d = await res.json()
        setError(d.detail ?? 'Revision failed')
      } else {
        setFeedback(''); setFeedbackOpen(false)
        onRefresh()
      }
    } catch (e) {
      setError('Network error')
    } finally {
      setLoading(false)
    }
  }

  // ── Stop job ──────────────────────────────────────────────────
  const handleStop = async () => {
    if (!window.confirm('Stop this job and mark it as FAILED?')) return
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/agent/stop/${job.job_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Stopped by user from dashboard' }),
      })
      if (!res.ok) {
        const d = await res.json()
        setError(d.detail ?? 'Stop failed')
      } else {
        onRefresh()
      }
    } catch (e) {
      setError('Network error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="agent-panel">
      {/* ── Header: ticket id + title + status ─────────────── */}
      <div className="panel-header">
        <div className="panel-header-left">
          <div className="panel-ticket-id">{job.ticket_id}</div>
          <div className="panel-title">{job.ticket_title}</div>
          <div className="panel-status-row">
            <StatusBadge status={job.status} />
            {job.branch_name && (
              <span style={{ fontSize: 11, color: 'var(--text-faint)', fontFamily: 'monospace' }}>
                {job.branch_name}
              </span>
            )}
            {job.pr_url && (
              <a className="panel-pr-link" href={job.pr_url} target="_blank" rel="noreferrer">
                View PR →
              </a>
            )}
          </div>
        </div>
      </div>

      {/* ── Body: plan details ──────────────────────────────── */}
      <div className="panel-body">

        {error && <div className="error-msg">{error}</div>}

        {/* Show waiting message while agent is still working */}
        {isActive && !plan && (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: '20px 0' }}>
            Agent is working… status updates arrive in real time via WebSocket.
          </div>
        )}

        {/* Plan is available once AWAITING_APPROVAL (or after) */}
        {plan && (
          <>
            {/* Questions — show prominently at the top if any */}
            {plan.questions?.length > 0 && (
              <div className="questions-box" style={{ marginBottom: 20 }}>
                <div className="questions-title">⚠️ Agent has questions — answer before approving</div>
                {plan.questions.map((q, i) => (
                  <div key={i} className="question-item">{q}</div>
                ))}
              </div>
            )}

            {/* Summary */}
            <div className="section">
              <div className="section-label">Summary</div>
              <div className="section-text">{plan.summary}</div>
            </div>

            {/* Risk level */}
            <div className="section">
              <div className="section-label">Risk Level</div>
              <span className={`risk-badge risk-${plan.risk_level?.toLowerCase()}`}>
                {plan.risk_level}
              </span>
            </div>

            {/* Files to modify */}
            {plan.files_to_modify?.length > 0 && (
              <div className="section">
                <div className="section-label">Files to Modify ({plan.files_to_modify.length})</div>
                <ul className="file-list">
                  {plan.files_to_modify.map((f, i) => (
                    <li key={i} className="file-item">
                      <span className="file-icon">✏️</span>{f}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Files to create */}
            {plan.files_to_create?.length > 0 && (
              <div className="section">
                <div className="section-label">Files to Create ({plan.files_to_create.length})</div>
                <ul className="file-list">
                  {plan.files_to_create.map((f, i) => (
                    <li key={i} className="file-item">
                      <span className="file-icon">🆕</span>{f}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Steps */}
            {plan.steps?.length > 0 && (
              <div className="section">
                <div className="section-label">Steps ({plan.steps.length})</div>
                <ul className="steps-list">
                  {plan.steps.map((s, i) => (
                    <li key={i} className="step-item">
                      <span className="step-num">{i + 1}</span>
                      <span className="step-text">{s}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        {/* Terminal state messages */}
        {job.status === 'COMPLETED' && (
          <div style={{ padding: '12px 0', color: 'var(--success)', fontSize: 13 }}>
            ✅ Job completed. Review the PR on GitHub, then label this example in the Fine-Tuning tab.
          </div>
        )}
        {job.status === 'FAILED' && (
          <div style={{ padding: '12px 0', color: 'var(--danger)', fontSize: 13 }}>
            ❌ Job failed. Check the backend logs for details.
          </div>
        )}
        {job.status === 'TIMED_OUT' && (
          <div style={{ padding: '12px 0', color: 'var(--danger)', fontSize: 13 }}>
            ⏱ Job timed out. The agent took too long at one of its steps.
          </div>
        )}
      </div>

      {/* ── Action buttons — only shown when plan needs approval ─ */}
      {isWaiting && plan && (
        <div className="actions-bar">
          {/* Primary actions row */}
          <div className="actions-row">
            <button className="btn-approve" onClick={handleApprove} disabled={loading}>
              ✓ Approve Plan
            </button>
            <button
              className={`btn-revise ${feedbackOpen ? 'open' : ''}`}
              onClick={() => setFeedbackOpen(!feedbackOpen)}
              disabled={loading}
            >
              {feedbackOpen ? '↑ Hide Feedback' : '↩ Give Feedback'}
            </button>
            <button className="btn-stop" onClick={handleStop} disabled={loading}>
              ✕
            </button>
          </div>

          {/* Feedback form — shown when user clicks "Give Feedback" */}
          {feedbackOpen && (
            <div className="feedback-box">
              <textarea
                placeholder="Tell the agent what to change. E.g. 'Also add unit tests for the new validator. The file path for the schema should be schemas/user.py not app/schemas.py.'"
                value={feedback}
                onChange={e => setFeedback(e.target.value)}
              />
              <button
                className="btn-submit-feedback"
                onClick={handleRevise}
                disabled={loading || !feedback.trim()}
              >
                {loading ? 'Revising…' : 'Submit Revision'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Stop button for active (non-approval) jobs */}
      {isActive && !isWaiting && (
        <div className="actions-bar">
          <div className="actions-row">
            <button className="btn-stop" style={{ flex: 1 }} onClick={handleStop} disabled={loading}>
              ✕ Stop Job
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
