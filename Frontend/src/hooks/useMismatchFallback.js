import { useEffect } from 'react';
import { BASE_URL } from '../config';

// If a validation result comes back without `mismatches`, fetch them
// separately from GET /api/reports/{run_id}/mismatches and merge them in
// via setResult once they arrive.
export function useMismatchFallback(result, setResult) {
  const runId = result?.run_id;
  const hasMismatches = !!result?.mismatches;

  useEffect(() => {
    if (!runId || hasMismatches) return undefined;

    let cancelled = false;
    fetch(`${BASE_URL}/api/reports/${runId}/mismatches`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) {
          setResult((prev) => (prev ? { ...prev, mismatches: data } : prev));
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [runId, hasMismatches, setResult]);
}
