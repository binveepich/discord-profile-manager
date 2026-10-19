import { useEffect, useState } from "react";
import { CheckCircle2, LoaderCircle, X, XCircle } from "lucide-react";
import { call } from "../api/bridge";
import { userError } from "../i18n";
import useDialogMotion from "../useDialogMotion";

export default function ProxyCheckDialog({ profile, onClose, notify }) {
  const [state, setState] = useState({ status: "starting" });
  const { closeDialog, dialogRef, backdropClassName, dialogClassName } = useDialogMotion(onClose);
  useEffect(() => {
    let timer; let active = true;
    (async () => {
      try {
        if (!profile?.proxy?.enabled) throw new Error("direct connection");
        const raw = `${profile.proxy.scheme}://${profile.proxy.host}:${profile.proxy.port}`;
        const jobId = await call("check_proxy", raw, 8);
        timer = window.setInterval(async () => { try { const next = await call("get_job", jobId); if (active) setState(next); if (["completed", "failed", "cancelled"].includes(next.status)) window.clearInterval(timer); } catch (error) { if (active) setState({ status: "failed", error: userError(error) }); window.clearInterval(timer); } }, 300);
      } catch (error) { if (active) setState({ status: "failed", error: error.message === "direct connection" ? "Hồ sơ đang dùng kết nối trực tiếp, không có Proxy để kiểm tra." : userError(error) }); }
    })();
    return () => { active = false; if (timer) window.clearInterval(timer); };
  }, [profile]);
  const result = state.result;
  const closeFromBackdrop = (event) => { if (event.target === event.currentTarget) closeDialog(); };
  return <div className={backdropClassName} onMouseDown={closeFromBackdrop}><div ref={dialogRef} tabIndex={-1} className={`modal-card max-w-md ${dialogClassName}`} role="dialog" aria-modal="true" aria-labelledby="proxy-check-title"><div className="modal-heading"><div><p className="eyebrow">Chẩn đoán Proxy</p><h2 id="proxy-check-title">{profile?.name}</h2></div><button className="icon-button" onClick={closeDialog} aria-label="Đóng"><X className="h-4 w-4" /></button></div><div className="space-y-4 p-6">{state.status === "running" || state.status === "starting" ? <div className="loading-line"><LoaderCircle className="spin-once h-5 w-5" /> Đang kiểm tra kết nối ra ngoài…</div> : result?.alive ? <div className="result-success"><div className="result-title"><CheckCircle2 className="h-5 w-5" /> Hoạt động</div><div className="metric-grid"><Metric label="IP bên ngoài" value={result.outbound_ip} /><Metric label="Độ trễ" value={`${result.latency_ms} ms`} /><Metric label="Quốc gia" value={result.country || "Chưa có"} /><Metric label="Thành phố" value={result.city || "Chưa có"} /><Metric label="Nhà cung cấp / ASN" value={[result.provider, result.asn].filter(Boolean).join(" · ") || "Chưa có"} /></div>{result.geography_warning && <p className="helper-copy">{result.geography_warning}</p>}</div> : <div className="result-error"><div className="result-title"><XCircle className="h-5 w-5" /> Không hoạt động</div><p>{result?.error || state.error || "Proxy không phản hồi."}</p></div>}<p className="helper-copy">Kiểm tra chạy ở nền. Thông tin vị trí chỉ mang tính tham khảo và có thể không có.</p></div><div className="modal-footer"><button className="secondary-button" onClick={closeDialog}>Đóng</button></div></div></div>;
}

function Metric({ label, value }) { return <div><p className="metric-label">{label}</p><p className="metric-value">{value}</p></div>; }
