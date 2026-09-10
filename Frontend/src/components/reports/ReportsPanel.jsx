import { FileSpreadsheet, FileText } from 'lucide-react';
import { BASE_URL } from '../../config';
import { ReportButton } from './ReportButton';

export function ReportsPanel({ runId, reportStatus, polling }) {
  const excelHref = reportStatus?.excel_ready ? `${BASE_URL}${reportStatus.excel_download_url}` : null;
  const docxHref = reportStatus?.docx_ready ? `${BASE_URL}${reportStatus.docx_download_url}` : null;

  return (
    <div className="dv-surface p-6 rounded-3xl flex flex-col sm:flex-row sm:items-center gap-5 sm:gap-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex-1 min-w-0">
        <h3 className="dv-font-display text-base font-bold mb-1" style={{ color: 'var(--text)' }}>
          Validation Reports
        </h3>
        <p className="text-sm mb-1" style={{ color: 'var(--text-muted)' }}>
          {polling
            ? 'Generating downloadable Excel and Word reports for this run…'
            : 'Reports for this run are ready to download.'}
        </p>
        <p className="dv-font-mono text-[11px]" style={{ color: 'var(--text-muted)', opacity: 0.7 }}>
          run_id: {runId}
        </p>
      </div>
      <div className="flex gap-3 flex-shrink-0">
        <ReportButton label="Excel Report" icon={FileSpreadsheet} ready={reportStatus?.excel_ready} href={excelHref} checking={polling} />
        <ReportButton label="Word Report" icon={FileText} ready={reportStatus?.docx_ready} href={docxHref} checking={polling} />
      </div>
    </div>
  );
}
