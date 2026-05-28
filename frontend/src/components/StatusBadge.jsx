import React from 'react'

// Human-readable labels for each status value
const LABELS = {
  QUEUED:             'Queued',
  GATHERING_CONTEXT:  'Gathering Context',
  PLANNING:           'Planning',
  AWAITING_APPROVAL:  'Needs Approval',
  EXECUTING:          'Executing',
  RAISING_PR:         'Raising PR',
  COMPLETED:          'Completed',
  FAILED:             'Failed',
  TIMED_OUT:          'Timed Out',
}

// Each status gets its own CSS class (defined in App.css)
// The dot pulses on EXECUTING and RAISING_PR to signal active work
export default function StatusBadge({ status }) {
  const label = LABELS[status] ?? status
  return (
    <span className={`badge badge-${status}`}>
      <span className={`badge-dot badge-dot-${status}`} />
      {label}
    </span>
  )
}
