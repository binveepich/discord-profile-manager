import { UI } from "../i18n";
import { DiscordIcon } from "./Header";

// The loading screen shown until the app is revealed. The looping sweep exists only while loading, and CSS removes it
// when reduced motion is on, which leaves the static bar and count.
export default function StartupSplash({ phase, progress, failure, onRetry }) {
  const blocked = phase === "blocked";
  const ready = phase === "mounting" || phase === "leaving";
  const fraction = ready ? 1 : progress.total ? progress.completed / progress.total : 0;
  const timedOut = Boolean(failure?.timedOut);

  return <div className="startup-splash" data-phase={phase} aria-busy={!blocked && !ready}>
    <div className="startup-card">
      <div className="startup-brand">
        <div className="brand-mark" aria-hidden="true"><DiscordIcon /></div>
        <h1 className="startup-title">{UI.appName}</h1>
      </div>
      {blocked ? (
        <div className="startup-error" role="alert">
          <p className="startup-error-title">{failure?.message}</p>
          <p className="startup-error-body">{timedOut ? "Quá thời gian chờ khi khởi động." : "Hãy bấm Thử lại. Nếu lỗi vẫn còn, hãy đóng và mở lại ứng dụng."}</p>
          {failure?.detail && <p className="startup-detail">{failure.detail}</p>}
          <button type="button" className="primary-button" onClick={onRetry}>Thử lại</button>
        </div>
      ) : (
        <>
          <p className="startup-status" role="status">{ready ? "Sẵn sàng" : progress.current || "Đang khởi động…"}</p>
          <div className="progress-track startup-track">
            <div className="progress-value" style={{ transform: `scaleX(${fraction})` }} />
            <span className="startup-sweep" aria-hidden="true" />
          </div>
          <p className="startup-count">{ready ? "" : `${progress.completed}/${progress.total}`}</p>
        </>
      )}
    </div>
  </div>;
}
