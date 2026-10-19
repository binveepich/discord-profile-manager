import { useState } from "react";
import { FileUp, X } from "lucide-react";
import { call } from "../api/bridge";
import { importResultNotificationType } from "../jobOutcome";
import { userError } from "../i18n";
import useDialogMotion from "../useDialogMotion";

export default function BatchImportDialog({ onClose, onDone, notify }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState("");
  const [progress, setProgress] = useState(null);
  const [summary, setSummary] = useState(null);
  const { closeDialog, dialogRef, backdropClassName, dialogClassName } = useDialogMotion(onClose);

  const importText = async () => {
    if (!text.trim()) return notify("Hãy nhập ít nhất một dòng tài khoản.", "error");
    setBusy(true); setSummary(null); setProgress(null);
    try {
      const job = await call("import_accounts_txt", text);
      let state;
      do { await new Promise((resolve) => setTimeout(resolve, 250)); state = await call("get_job", job); if (state.progress) setProgress(state.progress); } while (["queued", "running"].includes(state.status));
      if (state.status === "failed") throw new Error(state.error);
      const result = state.result || {};
      setSummary(result); notify(`Đã nhập: ${result.created || 0} tạo mới, ${result.skipped || 0} bỏ qua, ${result.failed || 0} thất bại.`, importResultNotificationType(result)); onDone(result);
    } catch (error) { const message = userError(error, "Không thể nhập dữ liệu. Vui lòng kiểm tra định dạng tệp."); setSummary({ total: progress?.total || 0, created: progress?.created || 0, skipped: progress?.skipped || 0, failed: progress?.failed || 0, errors: [{ line: "-", message }] }); notify(message, "error"); }
    finally { setBusy(false); }
  };

  const loadFile = (event) => { const file = event.target.files?.[0]; if (!file) return; setFileName(file.name); const reader = new FileReader(); reader.onload = () => setText(String(reader.result || "")); reader.readAsText(file); };
  const closeFromBackdrop = (event) => { if (event.target === event.currentTarget) closeDialog(); };
  return <div className={backdropClassName} onMouseDown={closeFromBackdrop}><div ref={dialogRef} tabIndex={-1} className={`modal-card max-w-xl ${dialogClassName}`} role="dialog" aria-modal="true" aria-labelledby="batch-import-title"><div className="modal-heading"><div><p className="eyebrow">Nhập hàng loạt</p><h2 id="batch-import-title">Thêm tài khoản từ TXT</h2></div><button className="icon-button" onClick={closeDialog} aria-label="Đóng"><X className="h-4 w-4" /></button></div><div className="space-y-4 p-6"><label className="secondary-button w-fit cursor-pointer"><FileUp className="h-4 w-4" />{fileName || "Chọn tệp TXT"}<input type="file" accept=".txt,text/plain" className="hidden" onChange={loadFile} /></label><textarea className="control min-h-[220px] w-full resize-y font-mono text-xs" placeholder={"mot@example.com:matkhau:2fa\nhai@example.com:matkhau"} value={text} onChange={(event) => setText(event.target.value)} /><p className="helper-copy">Bỏ qua dòng trống và dòng bắt đầu bằng #. Mỗi dòng hợp lệ tạo một hồ sơ, môi trường và cấu hình Autofill riêng. Dòng lỗi chỉ hiển thị số dòng cùng thông báo an toàn.</p>{busy && <div className="progress-box"><div className="progress-label"><span>Đang nhập ở nền</span><span>{progress?.completed || 0}/{progress?.total || 0}</span></div><div className="progress-track"><div className="progress-value" style={{ transform: `scaleX(${progress?.total ? (progress.completed || 0) / progress.total : 0})` }} /></div></div>}{summary && <div className="summary-box"><p>Tổng {summary.total || 0} · Tạo {summary.created || 0} · Bỏ qua {summary.skipped || 0} · Lỗi {summary.failed || 0}</p>{summary.errors?.length > 0 && <div className="error-list">{summary.errors.map((error) => <div key={`${error.line}-${error.message}`}>Dòng {error.line}: {error.message}</div>)}</div>}</div>}</div><div className="modal-footer"><button className="secondary-button" onClick={closeDialog}>Đóng</button><button className="primary-button" disabled={busy} onClick={importText}>{busy ? "Đang nhập…" : "Bắt đầu nhập"}</button></div></div></div>;
}
