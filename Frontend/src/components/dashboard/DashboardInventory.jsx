const TAG_STYLE = {
  source: { background: 'var(--surface-alt)', color: 'var(--text-muted)', border: '1px solid var(--border)' },
  target: { background: 'var(--accent-bg)', color: 'var(--accent-text)' },
};

const chip = (label, count, tone) => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.35rem',
      padding: '0.2rem 0.55rem',
      borderRadius: '9999px',
      fontSize: '0.7rem',
      fontWeight: 600,
      background: tone === 'bad' ? 'var(--danger-bg)' : 'var(--surface-alt)',
      color: tone === 'bad' ? 'var(--danger)' : 'var(--text-muted)',
      border: '1px solid var(--border)',
    }}
  >
    {label} <b>{count}</b>
  </span>
);

const toList = (items, keyFor) =>
  (items || [])
    .map((item) => (keyFor ? keyFor(item) ?? null : item))
    .filter((item) => item !== null && item !== undefined && String(item).trim() !== '');

const MAX_PREVIEW = 5;

function DetailList({ title, values }) {
  if (!values || values.length === 0) return null;
  const shown = values.slice(0, MAX_PREVIEW);
  const extra = values.length - shown.length;
  return (
    <li>
      <strong>{title}</strong>
      <ul style={{ paddingLeft: '1rem', margin: '0.15rem 0' }}>
        {shown.map((value, index) => (
          <li key={`${title}-${index}`} style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            {value}
          </li>
        ))}
        {extra > 0 && (
          <li style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>+{extra} more</li>
        )}
      </ul>
    </li>
  );
}

function visualDim(item) {
  const name = item?.title || item?.name;
  const type = item?.type || item?.visual_type;
  return type ? `${name || 'Untitled'} (${type})` : name || 'Untitled';
}

function DashboardPage({ pageEntry }) {
  const vd = (pageEntry && pageEntry.visual_data) || {};
  const visuals = toList(vd.visuals, visualDim);
  const kpis = toList(vd.kpi_cards, (k) => k.title || k.name);
  const filters = toList(vd.filters, (f) => {
    const name = f.name || f.title;
    const values = [].concat(f.selected_values || []).join(', ');
    return values ? `${name}: ${values}` : name;
  });
  const buttons = toList(vd.button_groups, (g) =>
    [].concat(g.buttons || []).map((b) => b.label || b.title).join(', '),
  );
  const tables = toList(
    vd.table_exports,
    (t) => t.dashboard_name || t.title || t.name,
  );
  const skipped = toList(
    (vd.skipped_visuals || []).map((s) => {
      const name = s.title || s.name || s.visual_name;
      const reason = s.reason || s.skip_reason;
      return reason ? `${name || 'Visual'}: ${reason}` : name;
    }),
  );
  const errors = toList(vd.errors, (e) => (typeof e === 'string' ? e : e.message || e.error));

  const pageName = (pageEntry?.dashboard && pageEntry.dashboard.page_name) || 'Page';
  const hasContent =
    visuals.length + kpis.length + filters.length + buttons.length + tables.length + skipped.length + errors.length > 0;

  return (
    <div className="dv-surface rounded-xl p-3">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <b style={{ fontSize: '0.82rem' }}>{pageName}</b>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
          {vd.status || 'no extraction'}
        </span>
      </div>
      <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
        {chip('Visuals', visuals.length)}
        {chip('KPIs', kpis.length)}
        {chip('Filters', filters.length)}
        {chip('Buttons', buttons.length)}
        {chip('Tables', tables.length)}
        {chip('Skipped', skipped.length)}
        {chip('Errors', errors.length, errors.length > 0 ? 'bad' : undefined)}
      </div>
      {hasContent && (
        <details style={{ marginTop: '0.5rem' }}>
          <summary style={{ fontSize: '0.75rem', cursor: 'pointer', color: 'var(--accent-text)' }}>
            View extracted details
          </summary>
          <ul style={{ margin: '0.5rem 0 0', paddingLeft: '0.75rem', listStyle: 'disc' }}>
            <DetailList title="Visuals" values={visuals} />
            <DetailList title="KPIs" values={kpis} />
            <DetailList title="Filters" values={filters} />
            <DetailList title="Button groups" values={buttons} />
            <DetailList title="Table exports" values={tables} />
            <DetailList title="Skipped visuals" values={skipped} />
            <DetailList title="Errors" values={errors} />
          </ul>
        </details>
      )}
    </div>
  );
}

export function DashboardInventory({ dashboards }) {
  const groups = [];
  const seen = new Map();
  for (const entry of dashboards || []) {
    const name = (entry?.dashboard && entry.dashboard.name) || 'Unknown';
    if (!seen.has(name)) {
      seen.set(name, []);
      groups.push(seen.get(name));
    }
    seen.get(name).push(entry);
  }

  if (groups.length === 0) return null;

  return (
    <div className="dv-surface rounded-3xl p-6">
      <h2 className="text-lg font-semibold" style={{ margin: 0 }}>
        DOM Extraction Results
      </h2>
      <p className="text-xs" style={{ color: 'var(--text-muted)', marginTop: '0.25rem' }}>
        Visual and structural data collected from the live Power BI DOM during capture. Expanded below each page for review.
      </p>
      <div className="grid md:grid-cols-2 gap-4" style={{ marginTop: '1rem' }}>
        {groups.map((entries, index) => {
          const side = index === 0 ? 'source' : 'target';
          const name = (entries[0]?.dashboard && entries[0].dashboard.name) || 'Unknown';
          return (
            <div key={`${side}-${name}`} className="space-y-3">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span
                  style={{
                    ...TAG_STYLE[side],
                    padding: '0.2rem 0.6rem',
                    borderRadius: '9999px',
                    fontSize: '0.68rem',
                    fontWeight: 700,
                  }}
                >
                  {side.toUpperCase()}
                </span>
                <b style={{ fontSize: '0.85rem' }}>{name}</b>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  {entries.length} page{entries.length === 1 ? '' : 's'}
                </span>
              </div>
              {entries.map((entry, i) => (
                <DashboardPage key={`${side}-${i}`} pageEntry={entry} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}