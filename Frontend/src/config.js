// Central place for backend endpoints. Change BASE_URL here (or better,
// swap it for an env var like import.meta.env.VITE_API_BASE_URL) rather
// than hunting through components.
export const BASE_URL = 'http://localhost:8000';
export const API_URL = `${BASE_URL}/api/validate`;

export const REPORT_POLL_INTERVAL_MS = 3000;
export const REPORT_POLL_MAX_ATTEMPTS = 20; // ~60s at 3s intervals
