import { UI } from "../i18n";

const tones = {
  Running: "status-running",
  Closed: "status-closed",
  Error: "status-error",
};

export default function StatusBadge({ status }) {
  const label = UI.status[status] || UI.status.Error;
  return <span className={`status-badge ${tones[status] || tones.Error}`}><span className="status-dot" />{label}</span>;
}
