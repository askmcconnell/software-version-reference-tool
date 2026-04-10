const LABELS = {
  eol:        'EOL',
  outdated:   'Outdated',
  no_patch:   'No Patch',
  supported:  'Supported',
  lts:        'LTS',
  unknown:    'Unknown',
  // job statuses
  pending:    'Waiting',
  processing: 'Processing',
  complete:   'Complete',
  failed:     'Failed',
}

const DOTS = {
  eol:        '●',
  outdated:   '◑',
  no_patch:   '●',
  supported:  '●',
  lts:        '●',
  unknown:    '○',
  pending:    '○',
  processing: '◉',
  complete:   '●',
  failed:     '●',
}

export default function StatusBadge({ status }) {
  const s = (status || 'unknown').toLowerCase()
  return (
    <span className={`badge-status badge-${s}`}>
      {DOTS[s] || '○'} {LABELS[s] || status}
    </span>
  )
}
