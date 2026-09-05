import { useEffect, useState } from 'react';
import { BASE_URL } from '../config';

// Pings GET /api/health once on mount and reports 'checking' | 'online' | 'offline'.
export function useApiHealth() {
  const [status, setStatus] = useState('checking');

  useEffect(() => {
    let cancelled = false;
    fetch(`${BASE_URL}/api/health`)
      .then((res) => {
        if (!cancelled) setStatus(res.ok ? 'online' : 'offline');
      })
      .catch(() => {
        if (!cancelled) setStatus('offline');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}
