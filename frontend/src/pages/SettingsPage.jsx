import { useEffect, useState } from "react";
import { Accessibility, Check, CircleAlert, Cpu, Eye, LoaderCircle, Puzzle, Save, X } from "lucide-react";
import { call } from "../api/bridge";
import { userError } from "../i18n";
import useDialogMotion from "../useDialogMotion";

const COLUMN_OPTIONS = [
  ["account", "Tài khoản", "Hiển thị định danh tài khoản"],
  ["environment", "Môi trường / Proxy", "Hiển thị preset và trạng thái Proxy"],
  ["last_opened", "Mở gần đây", "Hiển thị lần sử dụng gần nhất"],
];

export default function SettingsPage({ preferences, onPreferenceChange, notify, onClose }) {
  const [runtime, setRuntime] = useState(null);
  const [extensions, setExtensions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [savingExtension, setSavingExtension] = useState("");
  const { closeDialog, dialogRef, backdropClassName, dialogClassName } = useDialogMotion(onClose);

  useEffect(() => {
    let active = true;
    Promise.all([call("get_runtime_info"), call("get_extension_policy")])
      .then(([nextRuntime, nextExtensions]) => {
        if (active) {
          setRuntime(nextRuntime);
          setExtensions(nextExtensions);
        }
      })
      .catch((error) => { if (active) notify(userError(error), "error"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [notify]);

  const toggleColumn = (name) => {
    const current = new Set(preferences.visible_columns);
    current.has(name) ? current.delete(name) : current.add(name);
    onPreferenceChange({ visible_columns: [...current] });
  };

  const toggleExtension = async (name, enabled) => {
    setSavingExtension(name);
    try {
      setExtensions(await call("set_optional_extension_policy", name, enabled));
      notify(enabled ? "Đã bật tiện ích tùy chọn." : "Đã tắt tiện ích tùy chọn.");
    } catch (error) { notify(userError(error), "error"); }
    finally { setSavingExtension(""); }
  };

  const closeFromBackdrop = (event) => {
    if (event.target === event.currentTarget) closeDialog();
  };

  return (
    <div className={backdropClassName} onMouseDown={closeFromBackdrop}>
      <section ref={dialogRef} tabIndex={-1} className={`modal-card settings-modal ${dialogClassName}`} role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header className="dialog-header">
          <div>
            <p className="eyebrow">Tùy chỉnh ứng dụng</p>
            <h2 id="settings-title">Cài đặt</h2>
            <p className="dialog-description">Các lựa chọn này chỉ ảnh hưởng giao diện quản lý, không thay đổi dữ liệu Chromium.</p>
          </div>
          <div className="dialog-heading-actions"><span className="save-note"><Save className="h-4 w-4" /> Tự động lưu</span>
            <button className="icon-button tooltip-trigger" type="button" onClick={closeDialog} aria-label="Đóng cài đặt" data-tooltip="Đóng" title="Đóng"><X className="h-4 w-4" /></button>
          </div>
        </header>

        <div className="settings-modal-body">
          <section className="panel settings-card">
            <div className="settings-heading"><Eye className="settings-icon" /><div><h3>Cột hiển thị</h3><p>Bật hoặc tắt từng cột tùy chọn.</p></div></div>
            <div className="settings-body settings-options">
              {COLUMN_OPTIONS.map(([key, label, description]) => (
                <Toggle key={key} checked={preferences.visible_columns.includes(key)} onChange={() => toggleColumn(key)} label={label} description={description} />
              ))}
              <div className="required-column"><span>Trạng thái</span><span className="required-chip">Luôn hiển thị</span></div>
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-heading"><Accessibility className="settings-icon" /><div><h3>Chuyển động</h3><p>Giảm các hiệu ứng trang trí trong giao diện.</p></div></div>
            <div className="settings-body">
              <Toggle checked={preferences.reduce_motion} onChange={(value) => onPreferenceChange({ reduce_motion: value })} label="Giảm chuyển động" description="Tắt hoặc rút ngắn chuyển cảnh và hiệu ứng không cần thiết." />
              <p className="helper-copy settings-note">Cài đặt trợ năng giảm chuyển động của Windows cũng được tôn trọng.</p>
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-heading"><Cpu className="settings-icon" /><div><h3>Trình duyệt</h3><p>Thông tin runtime được đọc an toàn, không khởi chạy Chromium.</p></div></div>
            <div className="settings-body">
              {loading ? <div className="loading-line"><LoaderCircle className="spin-once h-4 w-4" /> Đang kiểm tra runtime…</div> : runtime ? (
                <div className="runtime-summary"><InfoRow label="Runtime" value={runtime.runtime_name} /><InfoRow label="Phiên bản" value={runtime.browser_version} /><div className={runtime.browser_available ? "runtime-ready" : "runtime-warning"}>{runtime.browser_available ? <Check className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />}{runtime.browser_available ? "Sẵn sàng sử dụng" : "Chưa tìm thấy browser/chrome.exe"}</div></div>
              ) : <p className="muted">Không thể đọc thông tin runtime.</p>}
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-heading"><Puzzle className="settings-icon" /><div><h3>Tiện ích</h3><p>Tiện ích bắt buộc luôn được bảo vệ; tiện ích tùy chọn áp dụng cho hồ sơ mới và lần mở tiếp theo.</p></div></div>
            <div className="settings-body settings-options settings-extension-list">
              {extensions?.required?.map((item) => <div className="extension-line" key={item.name}><div><strong>{item.display_name || item.name}</strong><span>Bắt buộc</span></div><Check className="status-check h-4 w-4" /></div>)}
              {extensions?.optional?.map((item) => <Toggle key={item.name} checked={item.enabled} disabled={savingExtension === item.name} onChange={(value) => toggleExtension(item.name, value)} label={item.display_name || item.name} description="Tiện ích tùy chọn cho hồ sơ mới và lần mở tiếp theo." />)}
              {extensions?.quarantined?.map((item) => <div className="warning-box" key={item.name}><CircleAlert className="h-4 w-4" /><span>{item.display_name || item.name}: đã được cách ly và không được nạp.</span></div>)}
              {!extensions && !loading && <p className="muted">Chưa đọc được chính sách tiện ích.</p>}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}

function Toggle({ checked, onChange, label, description, disabled = false }) {
  return <div className="setting-toggle"><div><strong>{label}</strong><p>{description}</p></div><button type="button" className={`toggle ${checked ? "toggle-on" : ""}`} onClick={() => onChange(!checked)} disabled={disabled} aria-pressed={checked} aria-label={label}><span /></button></div>;
}

function InfoRow({ label, value }) { return <div className="info-row"><span>{label}</span><strong>{value || "Không rõ"}</strong></div>; }
