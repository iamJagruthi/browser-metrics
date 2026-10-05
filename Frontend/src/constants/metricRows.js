// import {
//   Globe,
//   Clock3,
//   Camera,
//   Server,
//   Activity,
//   AlertTriangle,
//   BarChart3,
//   Monitor,
//   Search,
//   AlertCircle,
//   Filter,
// } from 'lucide-react';

// export const METRIC_ROWS = [
//   { key: 'http_status', label: 'HTTP Status', icon: Server },
//   { key: 'browser_launch_seconds', label: 'Browser Launch', icon: Globe, unit: 's' },
//   { key: 'page_load_seconds', label: 'Page Load', icon: Clock3, unit: 's' },
//   { key: 'dashboard_render_seconds', label: 'Dashboard Render', icon: Monitor, unit: 's' },
//   { key: 'filter_dashboard_render_seconds', label: 'Filter Dashboard Render', icon: Filter, unit: 's' },
//   { key: 'screenshot_seconds', label: 'Screenshot Time', icon: Camera, unit: 's' },
//   { key: 'total_execution_seconds', label: 'Total Execution', icon: Activity, unit: 's' },
//   { key: 'total_requests', label: 'Total Requests', icon: BarChart3 },
//   { key: 'failed_requests', label: 'Failed Requests', icon: AlertTriangle, alert: true },
//   { key: 'console_messages', label: 'Console Messages', icon: Search },
//   { key: 'page_errors', label: 'Page Errors', icon: AlertCircle, alert: true },
// ];
import {
  Globe,
  Clock3,
  Server,
  Monitor,
} from 'lucide-react';

export const METRIC_ROWS = [
  { key: 'http_status', label: 'HTTP Status', icon: Server },
  { key: 'browser_launch_seconds', label: 'Browser Launch', icon: Globe, unit: 's' },
  { key: 'page_load_seconds', label: 'Page Load', icon: Clock3, unit: 's' },
  { key: 'dashboard_render_seconds', label: 'Dashboard Render', icon: Monitor, unit: 's' },
];