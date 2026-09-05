import { useEffect, useRef, useState } from 'react';
import { BASE_URL, REPORT_POLL_INTERVAL_MS, REPORT_POLL_MAX_ATTEMPTS } from '../config';

// Polls GET /api/reports/{runId} until both the Excel and Word reports are
// ready, or maxAttempts is reached. Returns { reportStatus, polling }.
export function useReportPolling(runId) {
  const [reportStatus, setReportStatus] = useState(null);
  const [polling, setPolling] = useState(false);
  const timeoutRef = useRef(null);

  useEffect(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }

    if (!runId) {
      setReportStatus(null);
      setPolling(false);
      return undefined;
    }

    let cancelled = false;
    let attempts = 0;
    setPolling(true);
    setReportStatus(null);

    const poll = async () => {
      try {
        const res = await fetch(`${BASE_URL}/api/reports/${runId}`);
        if (!res.ok) throw new Error('report status check failed');
        const data = await res.json();
        if (cancelled) return;

        setReportStatus(data);
        attempts += 1;

        if ((data.excel_ready && data.docx_ready) || attempts >= REPORT_POLL_MAX_ATTEMPTS) {
          setPolling(false);
          return;
        }
        timeoutRef.current = setTimeout(poll, REPORT_POLL_INTERVAL_MS);
      } catch {
        if (!cancelled) setPolling(false);
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [runId]);

  return { reportStatus, polling };
}
