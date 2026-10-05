import { Loader2, PlayCircle } from 'lucide-react';
import { UrlField } from './UrlField';

const SOURCE_TAG_STYLE = {
  background: 'var(--surface-alt)',
  color: 'var(--text-muted)',
  border: '1px solid var(--border)',
};
const TARGET_TAG_STYLE = { background: 'var(--accent-bg)', color: 'var(--accent-text)' };

export function ValidationForm({ sourceUrl, setSourceUrl, targetUrl, setTargetUrl, handleSubmit, loading }) {
  return (
    <div className="dv-surface p-6 md:p-8 rounded-3xl animate-in fade-in zoom-in-95 duration-500">
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="grid md:grid-cols-2 gap-6">
          <UrlField
            tag="SOURCE"
            tagStyle={SOURCE_TAG_STYLE}
            value={sourceUrl}
            onChange={setSourceUrl}
            placeholder="https://app.powerbi.com/..."
          />
          <UrlField
            tag="TARGET"
            tagStyle={TARGET_TAG_STYLE}
            value={targetUrl}
            onChange={setTargetUrl}
            placeholder="https://app.powerbi.com/..."
          />
        </div>

        <div className="flex justify-center pt-1">
          <button
            type="submit"
            disabled={loading}
            className="dv-btn-primary group relative inline-flex items-center justify-center gap-2 px-8 py-3.5 font-semibold rounded-xl transition-all duration-300 w-full md:w-auto min-w-[220px]"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Validating…</span>
              </>
            ) : (
              <>
                <PlayCircle className="w-5 h-5 group-hover:scale-110 transition-transform duration-300" />
                <span>Run Validation</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
