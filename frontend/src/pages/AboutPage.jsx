import { useEffect, useState } from "react";
import { BookOpen, CheckCircle2, ExternalLink, GitBranch, Github, Layers3, LoaderCircle, Users } from "lucide-react";
import { call } from "../api/bridge";
import { UI, userError } from "../i18n";

export default function AboutPage({ notify }) {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    let active = true;
    call("get_about_info").then((value) => { if (active) setInfo(value); }).catch((error) => { if (active) notify(userError(error), "error"); });
    return () => { active = false; };
  }, [notify]);

  const data = info || { name: UI.appName, status: UI.devStatus, commit: "local", branch: "không xác định", contributors: [], stack: [] };
  return <main className="page-scroll"><div className="about-hero"><div className="about-mark">D</div><div><p className="eyebrow">Thông tin dự án</p><h2 className="page-title">{data.name}</h2><p className="page-description">{data.status}</p></div></div>
    <div className="about-grid"><section className="panel about-card"><div className="settings-heading"><GitBranch className="settings-icon" /><div><h3>Bản dựng hiện tại</h3><p>Thông tin được đọc từ Git của repository hiện tại.</p></div></div><div className="about-details"><Info label="Commit" value={data.commit} mono /><Info label="Nhánh" value={data.branch} mono /><Info label="Giấy phép" value={data.license || "Chưa xác định"} /></div>{data.repository && <a className="repository-link" href={data.repository} target="_blank" rel="noreferrer"><Github className="h-4 w-4" /> Mở repository <ExternalLink className="h-3.5 w-3.5" /></a>}</section>
      <section className="panel about-card"><div className="settings-heading"><Layers3 className="settings-icon" /><div><h3>Công nghệ</h3><p>Những thành phần chính của phiên bản phát triển.</p></div></div><div className="chip-list">{(data.stack || []).map((item) => <span className="tech-chip" key={item}>{item}</span>)}{!data.stack?.length && <span className="muted"><LoaderCircle className="mr-1 inline h-4 w-4" /> Đang tải…</span>}</div><div className="about-note"><CheckCircle2 className="h-4 w-4" /> Root runtime ổn định vẫn là legacy; bản này chưa phải bản phát hành cuối.</div></section>
      <section className="panel about-card about-wide"><div className="settings-heading"><Users className="settings-icon" /><div><h3>Đóng góp</h3><p>Tên được lấy từ lịch sử commit, không hiển thị email.</p></div></div>{data.contributors?.length ? <div className="contributor-list">{data.contributors.map((name) => <span key={name}>{name}</span>)}</div> : <p className="muted">Chưa có thông tin contributor từ Git.</p>}</section>
    </div>
    <div className="about-footnote"><BookOpen className="h-4 w-4" /> DPM ưu tiên sự ổn định, dữ liệu hồ sơ độc lập và các thao tác có thể kiểm soát.</div>
  </main>;
}

function Info({ label, value, mono = false }) { return <div className="info-row"><span>{label}</span><strong className={mono ? "mono-value" : ""}>{value || "Không rõ"}</strong></div>; }
