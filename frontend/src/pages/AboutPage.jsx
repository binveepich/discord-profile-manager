import { useEffect, useState } from "react";
import { ExternalLink, GitBranch, Github, UserRound, Users, X } from "lucide-react";
import { call, onBridgeReady } from "../api/bridge";
import { UI, userError } from "../i18n";
import useDialogMotion from "../useDialogMotion";

const DEVELOPER_NAME = "merino sầu riêng";
const DEVELOPER_URL = "https://github.com/binveepich";

export default function AboutPage({ notify, onClose, initialInfo = null }) {
  const [info, setInfo] = useState(initialInfo);
  const { closeDialog, dialogRef, backdropClassName, dialogClassName } = useDialogMotion(onClose);

  useEffect(() => {
    // The loading splash has already read this information, so the dialog does not read it again.
    if (initialInfo) return undefined;
    let active = true;
    const unsubscribe = onBridgeReady(() => {
      call("get_about_info").then((value) => { if (active) setInfo(value); }).catch((error) => { if (active) notify(userError(error), "error"); });
    });
    return () => { active = false; unsubscribe(); };
  }, [notify, initialInfo]);

  const closeFromBackdrop = (event) => {
    if (event.target === event.currentTarget) closeDialog();
  };
  const data = info || {
    name: UI.appName,
    status: UI.devStatus,
    commit: "…",
    branch: "…",
    repository: null,
    contributors: [DEVELOPER_NAME],
  };
  const contributors = Array.isArray(data.contributors) ? data.contributors : [DEVELOPER_NAME];
  const otherContributors = contributors.filter((name) => name && name !== DEVELOPER_NAME);

  return (
    <div className={backdropClassName} onMouseDown={closeFromBackdrop}>
      <section ref={dialogRef} tabIndex={-1} className={`modal-card about-modal ${dialogClassName}`} role="dialog" aria-modal="true" aria-labelledby="about-title">
        <header className="dialog-header about-dialog-header">
          <div className="about-title-block">
            <div className="about-mark"><DiscordIcon /></div>
            <div className="about-title-copy">
              <p className="eyebrow">Thông Tin</p>
              <h2 id="about-title">{data.name}</h2>
              <p className="dialog-description">{data.status}</p>
            </div>
          </div>
          <button className="icon-button tooltip-trigger" type="button" onClick={closeDialog} aria-label="Đóng Thông Tin" data-tooltip="Đóng" title="Đóng"><X className="h-4 w-4" /></button>
        </header>

        <div className="about-modal-body">
          <section className="panel about-card about-project-card">
            <div className="about-card-title"><GitBranch className="settings-icon" /><h3>Thông tin dự án</h3></div>
            <div className="about-details">
              <Info label="Dự án" value={data.name} />
              <Info label="Commit" value={data.commit} mono />
              <Info label="Nhánh" value={data.branch} mono />
            </div>
            {data.repository && <a className="repository-link" href={data.repository} target="_blank" rel="noreferrer"><Github className="h-4 w-4" /> Repository <ExternalLink className="h-3.5 w-3.5" /></a>}
          </section>

          <section className="panel contributor-card" aria-label="Nhà phát triển và cộng tác viên">
            <div className="about-card-title"><Users className="settings-icon" /><h3>Nhà phát triển</h3></div>
            <div className="contributor-row">
              <span className="contributor-identity"><span className="contributor-avatar"><UserRound className="h-4 w-4" /></span>
                <a className="developer-profile-link" href={DEVELOPER_URL} target="_blank" rel="noopener noreferrer">{DEVELOPER_NAME}<ExternalLink className="h-3 w-3" aria-hidden="true" /></a>
              </span>
              <span className="contributor-role">Dev chính</span>
            </div>
            {otherContributors.map((name) => <div className="contributor-row contributor-extra" key={name}><span className="contributor-identity"><span className="contributor-avatar"><UserRound className="h-4 w-4" /></span><strong>{name}</strong></span></div>)}
          </section>
        </div>
      </section>
    </div>
  );
}

function Info({ label, value, mono = false }) { return <div className="info-row"><span>{label}</span><strong className={mono ? "mono-value" : ""}>{value || "Không rõ"}</strong></div>; }

function DiscordIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M19.54 5.36A16.5 16.5 0 0 0 15.42 4l-.5 1.03a15.2 15.2 0 0 0-5.84 0L8.58 4a16.56 16.56 0 0 0-4.12 1.37C1.85 9.23 1.14 13 1.5 16.72a16.6 16.6 0 0 0 5.06 2.58l1.22-1.67c-.67-.25-1.3-.57-1.9-.95l.46-.36c3.67 1.7 8.2 1.7 11.83 0l.46.36c-.59.38-1.23.7-1.9.95l1.22 1.67a16.6 16.6 0 0 0 5.06-2.58c.42-4.32-.72-8.06-3.47-11.36ZM8.56 14.58c-1.1 0-2.01-1.02-2.01-2.27s.89-2.28 2.01-2.28 2.02 1.02 2.02 2.28-.9 2.27-2.02 2.27Zm6.88 0c-1.1 0-2.01-1.02-2.01-2.27s.89-2.28 2.01-2.28 2.02 1.02 2.02 2.28-.9 2.27-2.02 2.27Z" /></svg>;
}
