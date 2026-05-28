import React, { useState, useEffect } from 'react'

const API = 'http://localhost:8000'

// ──────────────────────────────────────────────────────────────
// Settings page — edit system prompts and model parameters
//
// Two tabs: Planner | Executor
// Each tab loads the current active PromptConfig from the DB.
//
// Save creates a NEW version in the DB (old versions are kept).
// Changes take effect on the next job run — no restart needed.
// ──────────────────────────────────────────────────────────────
export default function Settings() {
  const [step,         setStep        ] = useState('planner')
  const [prompt,       setPrompt      ] = useState(null)
  const [loading,      setLoading     ] = useState(true)
  const [saving,       setSaving      ] = useState(false)
  const [saved,        setSaved       ] = useState(false)
  const [error,        setError       ] = useState('')

  // Editable fields
  const [systemPrompt, setSystemPrompt] = useState('')
  const [customRules,  setCustomRules ] = useState('')
  const [temperature,  setTemperature ] = useState(0.4)
  const [maxTokens,    setMaxTokens   ] = useState(2048)
  const [topP,         setTopP        ] = useState(1.0)

  // ── Load prompt config for current step ─────────────────────
  useEffect(() => {
    const load = async () => {
      setLoading(true); setError(''); setSaved(false)
      try {
        const res = await fetch(`${API}/settings/prompt/${step}`)
        if (!res.ok) throw new Error(`${res.status}`)
        const data = await res.json()
        setPrompt(data)
        setSystemPrompt(data.system_prompt)
        setCustomRules(data.custom_rules)
        setTemperature(data.temperature)
        setMaxTokens(data.max_tokens)
        setTopP(data.top_p)
      } catch (e) {
        setError(`Failed to load ${step} prompt: ${e.message}`)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [step])

  // ── Save — creates a new version, deactivates old ───────────
  const handleSave = async () => {
    setSaving(true); setError(''); setSaved(false)
    try {
      const res = await fetch(`${API}/settings/prompt/${step}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system_prompt: systemPrompt,
          custom_rules:  customRules,
          temperature:   parseFloat(temperature),
          max_tokens:    parseInt(maxTokens),
          top_p:         parseFloat(topP),
        }),
      })
      if (!res.ok) {
        const d = await res.json()
        setError(d.detail ?? 'Save failed')
      } else {
        const data = await res.json()
        setPrompt(data)
        setSaved(true)
        setTimeout(() => setSaved(false), 3000)
      }
    } catch (e) {
      setError('Network error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="settings-page">
      <div className="settings-title">Settings</div>
      <div className="settings-sub">
        Edit system prompts and model parameters. Changes take effect on the next job run.
        Every save creates a new version — old versions are never deleted.
      </div>

      {/* ── Step tabs ─────────────────────────────────────── */}
      <div className="settings-tabs">
        {['planner', 'executor'].map(s => (
          <button
            key={s}
            className={`settings-tab ${step === s ? 'active' : ''}`}
            onClick={() => setStep(s)}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
            {prompt && step === s && (
              <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.6 }}>v{prompt.version}</span>
            )}
          </button>
        ))}
      </div>

      {loading && <div className="loading">Loading…</div>}
      {error   && <div className="error-msg">{error}</div>}

      {!loading && prompt && (
        <>
          {/* ── System Prompt ────────────────────────────── */}
          <div className="settings-card">
            <div className="settings-card-title">System Prompt</div>
            <div className="settings-card-desc">
              The base instruction the LLM receives before every job.
              Controls tone, format, and general behaviour.
            </div>
            <div className="field">
              <textarea
                value={systemPrompt}
                onChange={e => setSystemPrompt(e.target.value)}
                style={{ minHeight: 280, fontFamily: 'SF Mono, Fira Code, monospace', fontSize: 12, lineHeight: 1.6 }}
              />
            </div>
          </div>

          {/* ── Custom Rules ─────────────────────────────── */}
          <div className="settings-card">
            <div className="settings-card-title">Custom Rules</div>
            <div className="settings-card-desc">
              Project-specific rules appended to every prompt.
              Example: "Always use async/await. Max line length 88 characters."
            </div>
            <div className="field">
              <textarea
                value={customRules}
                onChange={e => setCustomRules(e.target.value)}
                placeholder="e.g. Always write unit tests. Never use synchronous DB calls."
                style={{ minHeight: 100 }}
              />
            </div>
          </div>

          {/* ── Model Parameters ─────────────────────────── */}
          <div className="settings-card">
            <div className="settings-card-title">Model Parameters</div>
            <div className="settings-card-desc">
              Control how the LLM generates output for this step.
              Low temperature = deterministic code. Higher = creative planning.
            </div>

            <div className="field-row">
              {/* Temperature */}
              <div className="slider-group">
                <div className="slider-top">
                  <span className="slider-label">Temperature</span>
                  <span className="slider-value">{parseFloat(temperature).toFixed(2)}</span>
                </div>
                <input
                  type="range" min="0" max="1" step="0.05"
                  value={temperature}
                  onChange={e => setTemperature(e.target.value)}
                />
                <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 3 }}>
                  0.1 for code · 0.4–0.6 for planning
                </div>
              </div>

              {/* Top-P */}
              <div className="slider-group">
                <div className="slider-top">
                  <span className="slider-label">Top-P</span>
                  <span className="slider-value">{parseFloat(topP).toFixed(2)}</span>
                </div>
                <input
                  type="range" min="0.1" max="1" step="0.05"
                  value={topP}
                  onChange={e => setTopP(e.target.value)}
                />
                <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 3 }}>
                  Keep at 0.9–1.0 for most cases
                </div>
              </div>

              {/* Max Tokens */}
              <div className="slider-group">
                <div className="slider-top">
                  <span className="slider-label">Max Tokens</span>
                  <span className="slider-value">{parseInt(maxTokens)}</span>
                </div>
                <input
                  type="range" min="512" max="8192" step="256"
                  value={maxTokens}
                  onChange={e => setMaxTokens(e.target.value)}
                />
                <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 3 }}>
                  2048 plan · 4096 code execution
                </div>
              </div>
            </div>
          </div>

          {/* ── Save button ───────────────────────────────── */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 4 }}>
            <button className="btn-save" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
            {saved && <span className="save-success">✓ Saved as version {prompt.version}</span>}
          </div>
        </>
      )}
    </div>
  )
}
