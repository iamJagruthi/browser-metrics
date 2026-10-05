import { useState } from 'react';
import { Loader2, PlayCircle, Upload, FileSpreadsheet } from 'lucide-react';
import { EXCEL_VALIDATE_URL } from '../../config';
import { ErrorBanner } from '../form/ErrorBanner';
import { ExcelResultPanel } from './ExcelResultPanel';

const FILE_TAG_STYLE = {
  background: 'var(--surface-alt)',
  color: 'var(--text-muted)',
  border: '1px solid var(--border)',
};

const extractErrorDetail = async (res) => {
  const data = await res.json().catch(() => ({}));
  return data.detail || `Request failed with status ${res.status}`;
};

function FileUploader({ tag, file, onSelect }) {
  return (
    <label
      className="block cursor-pointer p-5 rounded-2xl transition-all duration-200"
      style={{ border: '2px dashed var(--border)', background: 'var(--surface-alt)' }}
    >
      <input
        type="file"
        accept=".xlsx,.csv"
        className="hidden"
        onChange={(e) => onSelect(e.target.files?.[0] || null)}
      />
      <span className="flex items-center gap-2 text-sm font-semibold mb-3">
        <span
          className="dv-font-mono text-[10px] font-bold px-1.5 py-0.5 rounded"
          style={FILE_TAG_STYLE}
        >
          {tag}
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
          <FileSpreadsheet className="w-3.5 h-3.5" /> .xlsx or .csv
        </span>
      </span>
      <span className="flex items-center gap-2">
        <Upload className="w-4 h-4" style={{ color: 'var(--accent-text)' }} />
        <span className="text-sm truncate" style={{ color: file ? 'var(--text)' : 'var(--text-muted)' }}>
          {file ? file.name : `Choose ${tag.toLowerCase()} file…`}
        </span>
      </span>
    </label>
  );
}

export function ExcelValidation() {
  const [sourceFile, setSourceFile] = useState(null);
  const [targetFile, setTargetFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setResult(null);

    if (!sourceFile) {
      setError('Missing source file. Choose a source Excel/CSV file first.');
      return;
    }
    if (!targetFile) {
      setError('Missing target file. Choose a target Excel/CSV file first.');
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append('source_file', sourceFile);
    formData.append('target_file', targetFile);

    try {
      const res = await fetch(EXCEL_VALIDATE_URL, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        throw new Error(await extractErrorDetail(res));
      }
      const data = await res.json();
      setResult(data);
    } catch (err) {
      setError(err.message || 'Something went wrong while validating the files.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="dv-surface p-6 md:p-8 rounded-3xl animate-in fade-in zoom-in-95 duration-500">
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="grid md:grid-cols-2 gap-6">
            <FileUploader tag="SOURCE" file={sourceFile} onSelect={setSourceFile} />
            <FileUploader tag="TARGET" file={targetFile} onSelect={setTargetFile} />
          </div>

          <div className="flex justify-center pt-1">
            <button
              type="submit"
              disabled={loading}
              className="dv-btn-primary group relative inline-flex items-center justify-center gap-2 px-8 py-3.5 font-semibold rounded-xl transition-all duration-300 w-full md:w-auto min-w-[240px]"
            >
              {loading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Comparing…</span>
                </>
              ) : (
                <>
                  <PlayCircle className="w-5 h-5 group-hover:scale-110 transition-transform duration-300" />
                  <span>Run Excel Validation</span>
                </>
              )}
            </button>
          </div>
          <p className="text-center text-xs" style={{ color: 'var(--text-muted)' }}>
            Compares every shared sheet between the two files using the deterministic table comparison engine. No browser and no AI is involved.
          </p>
        </form>
      </div>

      <ErrorBanner message={error} />
      {result && <ExcelResultPanel result={result} />}
    </div>
  );
}