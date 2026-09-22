import { useEffect, useState } from "react";
import { Check, CircleAlert, Cpu, Eye, LoaderCircle, Palette, Puzzle, Save, SlidersHorizontal } from "lucide-react";
import { call } from "../api/bridge";
import { UI, userError } from "../i18n";

const COLUMN_OPTIONS = [
  ["account", "Tài khoản", "Hiển thị định danh tài khoản an toàn"],
  ["environment", "Môi trường / Proxy", "Hiển thị preset và trạng thái Proxy"],
  ["status", "Trạng thái", "Hiển thị hồ sơ đang mở hay đã đóng"],
  ["last_opened", "Mở gần đây", "Hiển thị thời điểm sử dụng gần nhất"],
];

export default function SettingsPage({ preferences, onPreferenceChange, notify }) {
  const [runtime, setRuntime] = useState(null);
  const [extensions, setExtensions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [savingExtension, setSavingExtension] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([call("get_runtime_info"), call("get_extension_policy")])
      .then(([nextRuntime, nextExtensions]) => { if (active) { setRuntime(nextRuntime); setExtensions(nextExtensions); } })
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
    } catch (error) { notify(userError(error), "error"); } finally { setSavingExtension(""); }
  };

  return <main className="page-scroll"><div className="page-header"><div><p className="eyebrow">Tùy chỉnh ứng dụng</p><h2 className="page-title">Cài đặt</h2><p className="page-description">Các lựa chọn này chỉ ảnh hưởng giao diện quản lý, không thay đổi dữ liệu Chromium của hồ sơ.</p></div><div className="save-note"><Save className="h-4 w-4" /> Tự động lưu</div></div>
    <div className="settings-grid">
      <section className="panel settings-card"><div className="settings-heading"><Palette className="settings-icon" /><div><h3>Giao diện</h3><p>Chọn cách hiển thị phù hợp với môi trường làm việc.</p></div></div><div className="settings-body">
        <label className="field-label">Chủ đề<select className="control mt-2 w-full" value={preferences.theme} onChange={(event) => onPreferenceChange({ theme: event.target.value })}><option value="system">{UI.theme.system}</option><option value="light">{UI.theme.light}</option><option value="dark">{UI.theme.dark}</option></select></label>
        <label className="field-label">Mật độ bảng hồ sơ<select className="control mt-2 w-full" value={preferences.density} onChange={(event) => onPreferenceChange({ density: event.target.value })}><option value="comfortable">Thoải mái</option><option value="compact">Gọn</option></select></label>
        <Toggle checked={preferences.reduce_motion} onChange={(value) => onPreferenceChange({ reduce_motion: value })} label="Giảm chuyển động" description="Tắt các hiệu ứng không cần thiết để dễ tập trung." />
        <Toggle checked={preferences.sidebar_collapsed} onChange={(value) => onPreferenceChange({ sidebar_collapsed: value })} label="Ẩn bảng tác vụ bên phải" description="Mở rộng không gian bảng khi bạn chỉ làm việc với danh sách." />
      </div></section>

      <section className="panel settings-card"><div className="settings-heading"><Eye className="settings-icon" /><div><h3>Cột hiển thị</h3><p>Giữ lại thông tin cần thiết cho bảng hồ sơ.</p></div></div><div className="settings-body settings-options">{COLUMN_OPTIONS.map(([key, label, description]) => <Toggle key={key} checked={preferences.visible_columns.includes(key)} onChange={() => toggleColumn(key)} label={label} description={description} />)}</div></section>

      <section className="panel settings-card"><div className="settings-heading"><Cpu className="settings-icon" /><div><h3>Trình duyệt</h3><p>Thông tin runtime được đọc an toàn, không tự khởi chạy Chromium.</p></div></div><div className="settings-body">{loading ? <div className="loading-line"><LoaderCircle className="spin-once h-4 w-4" /> Đang kiểm tra runtime…</div> : runtime ? <div className="runtime-summary"><InfoRow label="Runtime" value={runtime.runtime_name} /><InfoRow label="Phiên bản" value={runtime.browser_version} /><div className={runtime.browser_available ? "runtime-ready" : "runtime-warning"}>{runtime.browser_available ? <Check className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />}{runtime.browser_available ? "Sẵn sàng sử dụng" : "Chưa tìm thấy browser/chrome.exe"}</div></div> : <p className="muted">Không thể đọc thông tin runtime.</p>}</div></section>

      <section className="panel settings-card"><div className="settings-heading"><Puzzle className="settings-icon" /><div><h3>Tiện ích</h3><p>Tiện ích bắt buộc luôn được bảo vệ; tiện ích tùy chọn có thể bật hoặc tắt.</p></div></div><div className="settings-body settings-options">{extensions?.required?.map((item) => <div className="extension-line" key={item.name}><div><strong>{item.display_name || item.name}</strong><span>Bắt buộc</span></div><Check className="status-check h-4 w-4" /></div>)}{extensions?.optional?.map((item) => <Toggle key={item.name} checked={item.enabled} disabled={savingExtension === item.name} onChange={(value) => toggleExtension(item.name, value)} label={item.display_name || item.name} description="Tiện ích tùy chọn cho các hồ sơ mới và lần mở tiếp theo." />)}{extensions?.quarantined?.map((item) => <div className="warning-box" key={item.name}><CircleAlert className="h-4 w-4" /><span>{item.display_name || item.name}: đã được cách ly và không được nạp.</span></div>)}{!extensions && !loading && <p className="muted">Chưa đọc được chính sách tiện ích.</p>}</div></section>
    </div>
  </main>;
}

function Toggle({ checked, onChange, label, description, disabled = false }) {
  return <div className="setting-toggle"><div><strong>{label}</strong><p>{description}</p></div><button type="button" className={`toggle ${checked ? "toggle-on" : ""}`} onClick={() => onChange(!checked)} disabled={disabled} aria-pressed={checked} aria-label={label}><span /></button></div>;
}

function InfoRow({ label, value }) { return <div className="info-row"><span>{label}</span><strong>{value || "Không rõ"}</strong></div>; }
