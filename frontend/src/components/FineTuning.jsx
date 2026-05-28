import React, { useState, useEffect } from 'react'
import StatusBadge from './StatusBadge'

const API = 'http://localhost:8000'

// ──────────────────────────────────────────────────────────────
// FineTuning page — label completed jobs and trigger training
//
// Flow:
//  1. User reviews PR on GitHub
//  2. Comes here and clicks Approve (good code) or Reject (bad code)
//  3. Approve  → POST /finetuning/approve/{job_id}
//               stores a vector embedding + marks training example "approved"
//  4. Reject   → POST /finetuning/reject/{job_id} with reason
//               marks training example "rejected" with reason (LLM learns from this)
//  5. Once 10+ approved examples: Export JSONL → Start Fine-Tuning
// ──────────────────────────────────────────────────────────────
export default function FineTuning({ jobs, onRefresh }) {
  const [counts,      setCounts     ] = useState(null)
  const [labels,      setLabels     ] = useState({})     // { job_id: 'approved'|'rejected' }
  const [rejectOpen,  setRejectOpen ] = useState(null)   // job_id with reject form open
  const [rejectText,  setRejectText ] = useState('')
  const [ftJobId,     setFtJobId    ] = useState('')
  const [ftStatus,    setFtStatus   ] = useState(null)
  const [msg,         setMsg        ] = useState({ text: '', type: '' })
  const [loading,     setLoading    ] = useState(false)

  // ── Load example counts ──────────────────────────────────────
  const loadCounts = async () => {
    try {
      const res = await fetch(`${API}/finetuning/examples`)
      setCounts(await res.json())
    } catch (e) {
      console.error('loadCounts failed:', e)
    }
  }

  useEffect(() => { loadCounts() }, [jobs])

  // Only show jobs that have completed (COMPLETED, FAILED, TIMED_OUT)
  const doneJobs = jobs.filter(j =>
    ['COMPLETED', 'FAILED', 'TIMED_OUT'].includes(j.status)
  )

  // ── Approve a training example ───────────────────────────────
  const handleApprove = async (jobId) => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/finetuning/approve/${jobId}`, { method: 'POST' })
      if (!res.ok) {
        const d = await res.json()
        setMsg({ text: d.detail ?? 'Approve failed', type: 'error' })
      } else {
        setLabels(p => ({ ...p, [jobId]: 'approved' }))
        setMsg({ text: 'Marked approved. Embedding stored for vector search.', type: 'success' })
        loadCounts()
      }
    } catch (e) {
      setMsg({ text: 'Network error', type: 'error' })
    } finally {
      setLoading(false)
    }
  }

  // ── Reject a training example ────────────────────────────────
  const handleReject = async (jobId) => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/finetuning/reject/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: rejectText.trim() || null }),
      })
      if (!res.ok) {
        const d = await res.json()
        setMsg({ text: d.detail ?? 'Reject failed', type: 'error' })
      } else {
        setLabels(p => ({ ...p, [jobId]: 'rejected' }))
        setRejectOpen(null); setRejectText('')
        setMsg({ text: 'Marked rejected. Reason saved for LLM learning.', type: 'success' })
        loadCounts()
      }
    } catch (e) {
      setMsg({ text: 'Network error', type: 'error' })
    } finally {
      setLoading(false)
    }
  }

  // ── Export JSONL ─────────────────────────────────────────────
  const handleExport = async () => {
    setLoading(true); setMsg({ text: '', type: '' })
    try {
      const res = await fetch(`${API}/finetuning/export`, { method: 'POST' })
      const d   = await res.json()
      if (!res.ok) {
        setMsg({ text: d.detail ?? 'Export failed', type: 'error' })
      } else {
        setMsg({ text: `Exported to: ${d.file_path}`, type: 'success' })
      }
    } catch (e) {
      setMsg({ text: 'Network error', type: 'error' })
    } finally {
      setLoading(false)
    }
  }

  // ── Start fine-tuning ────────────────────────────────────────
  const handleFinetune = async () => {
    if (!window.confirm('Export training data and submit to OpenAI for fine-tuning? This takes 30–60 minutes.')) return
    setLoading(true); setMsg({ text: '', type: '' })
    try {
      const res = await fetch(`${API}/finetuning/start`, { method: 'POST' })
      const d   = await res.json()
      if (!res.ok) {
        setMsg({ text: d.detail ?? 'Failed to start fine-tuning', type: 'error' })
      } else {
        setFtJobId(d.job_id)
        setMsg({ text: `Fine-tuning started. Job ID: ${d.job_id}`, type: 'success' })
      }
    } catch (e) {
      setMsg({ text: 'Network error', type: 'error' })
    } finally {
      setLoading(false)
    }
  }

  // ── Check fine-tune status ───────────────────────────────────
  const handleCheckStatus = async () => {
    if (!ftJobId.trim()) return
    setLoading(true)
    try {
      const res = await fetch(`${API}/finetuning/status/${ftJobId.trim()}`)
      const d   = await res.json()
      if (!res.ok) {
        setMsg({ text: d.detail ?? 'Status check failed', type: 'error' })
      } else {
        setFtStatus(d)
      }
    } catch (e) {
      setMsg({ text: 'Network error', type: 'error' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="ft-page">
      <div className="ft-title">Fine-Tuning</div>
      <div className="ft-sub">
        Label completed jobs after reviewing the PR on GitHub.
        Approved examples teach the agent what "good" looks like for your codebase.
        Rejected examples (with a reason) teach it what to avoid.
      </div>

      {/* ── Training example counts ──────────────────────── */}
      {counts && (
        <div className="stats-row">
          <div className="stat-card stat-approved">
            <div className="stat-value">{counts.approved}</div>
            <div className="stat-label">Approved</div>
          </div>
          <div className="stat-card stat-rejected">
            <div className="stat-value">{counts.rejected}</div>
            <div className="stat-label">Rejected</div>
          </div>
          <div className="stat-card stat-pending">
            <div className="stat-value">{counts.pending}</div>
            <div className="stat-label">Pending Review</div>
          </div>
          <div className="stat-card stat-total">
            <div className="stat-value">{counts.total_useful}</div>
            <div className="stat-label">Total Useful</div>
          </div>
        </div>
      )}

      {/* ── Job review list ────────────────────────────────── */}
      <div className="ft-section-title">Completed Jobs — Review & Label</div>

      {doneJobs.length === 0 && (
        <div style={{ color: 'var(--text-faint)', fontSize: 13, padding: '16px 0' }}>
          No completed jobs yet. Assign a ticket and let the agent finish to see jobs here.
        </div>
      )}

      {doneJobs.map(j => {
        const label     = labels[j.job_id]   // 'approved' | 'rejected' | undefined
        const isRejOpen = rejectOpen === j.job_id

        return (
          <div key={j.job_id}>
            <div className="job-review-card">
              <div className="job-review-info">
                <div className="job-review-id">{j.ticket_id}</div>
                <div className="job-review-title">{j.ticket_title}</div>
                {j.pr_url && (
                  <a href={j.pr_url} target="_blank" rel="noreferrer"
                     style={{ fontSize: 11, color: 'var(--info)', marginTop: 4, display: 'inline-block' }}>
                    View PR →
                  </a>
                )}
              </div>
              <div className="job-review-actions">
                <StatusBadge status={j.status} />
                {label ? (
                  // Already labelled — show chip
                  <span className={`label-chip label-${label}`}>
                    {label === 'approved' ? '✓ Approved' : '✕ Rejected'}
                  </span>
                ) : (
                  // Not yet labelled — show approve/reject buttons
                  <>
                    <button
                      className="btn-ft-approve"
                      onClick={() => handleApprove(j.job_id)}
                      disabled={loading}
                    >
                      ✓ Approve
                    </button>
                    <button
                      className="btn-ft-reject"
                      onClick={() => {
                        setRejectOpen(isRejOpen ? null : j.job_id)
                        setRejectText('')
                      }}
                      disabled={loading}
                    >
                      ✕ Reject
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Reject reason form — inline below the card */}
            {isRejOpen && !label && (
              <div style={{ padding: '8px 16px 12px', background: 'var(--surface)', border: '1px solid var(--border)', borderTop: 'none', borderRadius: '0 0 var(--radius) var(--radius)', marginBottom: 8, marginTop: -7 }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
                  Describe what was wrong — be specific. The LLM learns from this.
                </div>
                <div className="reject-form">
                  <textarea
                    value={rejectText}
                    onChange={e => setRejectText(e.target.value)}
                    placeholder="e.g. Executor added extra imports not in the plan and modified the wrong function. It also hallucinated a file path that doesn't exist."
                  />
                  <div className="reject-form-row">
                    <button className="btn-cancel" onClick={() => setRejectOpen(null)}>Cancel</button>
                    <button
                      className="btn-confirm-reject"
                      onClick={() => handleReject(j.job_id)}
                      disabled={loading}
                    >
                      {loading ? 'Saving…' : 'Confirm Reject'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )
      })}

      {/* ── Status message ────────────────────────────────── */}
      {msg.text && (
        <div className={`ft-msg ${msg.type}`}>{msg.text}</div>
      )}

      {/* ── Export / Fine-tune actions ─────────────────────── */}
      <div className="ft-actions">
        <button className="btn-export" onClick={handleExport} disabled={loading}>
          Export JSONL
        </button>
        <button
          className="btn-finetune"
          onClick={handleFinetune}
          disabled={loading || (counts && !counts.ready_to_finetune)}
        >
          {loading ? 'Working…' : 'Start Fine-Tuning'}
        </button>
      </div>

      {counts && !counts.ready_to_finetune && (
        <div className="ft-msg">
          You need at least 1 approved example to start fine-tuning. ({counts.approved} collected)
        </div>
      )}

      {/* ── Check fine-tune job status ─────────────────────── */}
      {ftJobId && (
        <div style={{ marginTop: 24, padding: 16, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>Fine-Tune Job Status</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input
              value={ftJobId}
              onChange={e => setFtJobId(e.target.value)}
              style={{ flex: 1 }}
              placeholder="Fine-tune job ID"
            />
            <button className="btn-save" onClick={handleCheckStatus} disabled={loading}>
              Check Status
            </button>
          </div>
          {ftStatus && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 5 }}>
              <div>Status: <strong style={{ color: 'var(--text)' }}>{ftStatus.status}</strong></div>
              <div>Model: <span style={{ fontFamily: 'monospace' }}>{ftStatus.model}</span></div>
              {ftStatus.fine_tuned_model && (
                <div style={{ color: 'var(--success)' }}>
                  ✓ Fine-tuned model: <span style={{ fontFamily: 'monospace' }}>{ftStatus.fine_tuned_model}</span>
                </div>
              )}
              {ftStatus.trained_tokens && (
                <div>Trained tokens: {ftStatus.trained_tokens.toLocaleString()}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
