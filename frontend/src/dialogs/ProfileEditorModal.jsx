import { useEffect, useState } from "react";
import { KeyRound, Network, RefreshCw, Save, X } from "lucide-react";
import { call } from "../api/bridge";
import { userError } from "../i18n";
import useDialogMotion from "../useDialogMotion";

const EMPTY_ENV = { window_width: "", window_height: "", language: "", language_order: "", region: "", timezone: "", user_agent: "", mobile_mode: false, touch_mode: false };

function displayNameFromEmail(value) { return String(value || "").split("@", 1)[0].replace(/[<>:/\\|?*\x00-\x1f]/g, "").trim(); }
function presetFor(environment) { const value = String(environment?.preset || "").toLowerCase(); return value === "auto" || value === "generated" || value === "default" ? "Auto" : value.includes("android") || value === "mobile" ? "Mobile" : value === "custom" ? "Custom" : "Desktop"; }
function environmentFields(environment) { return { window_width: environment?.window_width ?? environment?.window_geometry?.width ?? "", window_height: environment?.window_height ?? environment?.window_geometry?.height ?? "", language: environment?.language ?? "", language_order: Array.isArray(environment?.language_order) ? environment.language_order.join(", ") : environment?.language_order ?? "", region: environment?.region ?? "", timezone: environment?.timezone ?? "", user_agent: environment?.user_agent ?? "", mobile_mode: Boolean(environment?.mobile_mode), touch_mode: Boolean(environment?.touch_mode) }; }

export default function ProfileEditorModal({ profile, onClose, onSaved, notify }) {
  const { closeDialog, dialogRef, backdropClassName, dialogClassName } = useDialogMotion(onClose);
  const existing = profile?.environment || {};
  const [tab, setTab] = useState("account");
  const [accountMode, setAccountMode] = useState("fast");
  const [nameTouched, setNameTouched] = useState(Boolean(profile));
  const [accountDirty, setAccountDirty] = useState(false);
  const [runtime, setRuntime] = useState(null);
  const [environmentMeta, setEnvironmentMeta] = useState(existing);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [environmentDirty, setEnvironmentDirty] = useState(false);
  const [proxyDirty, setProxyDirty] = useState(false);
  const [proxyCredentialsDirty, setProxyCredentialsDirty] = useState(false);
  const [form, setForm] = useState({ name: profile?.name || "", fastInput: "", email: profile?.account || "", password: "", totp_secret: "", environment: profile ? presetFor(existing) : "Auto", enabled: Boolean(profile?.proxy?.enabled), scheme: profile?.proxy?.scheme || "http", host: profile?.proxy?.host || "", port: profile?.proxy?.port || "", username: "", proxy_password: "", proxy_input: "", ...EMPTY_ENV, ...environmentFields(existing) });

  useEffect(() => { call("get_runtime_info").then(setRuntime).catch(() => {}); }, []);
  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const updateEmail = (value) => { setAccountDirty(true); setForm((current) => ({ ...current, email: value, name: !nameTouched ? displayNameFromEmail(value) : current.name })); };
  const updateFast = (value) => { setAccountDirty(true); setForm((current) => ({ ...current, fastInput: value, name: !nameTouched ? displayNameFromEmail(value.split(":", 1)[0]) : current.name })); };
  const updateEnvironment = (key, value) => {
    setEnvironmentDirty(true);
    setForm((current) => ({ ...current, environment: "Custom", [key]: value }));
  };
  const updateProxy = (key, value) => {
    setProxyDirty(true);
    if (key === "username" || key === "proxy_password") setProxyCredentialsDirty(true);
    update(key, value);
  };

  const environmentPayload = () => {
    if (form.environment === "Auto") return { preset: "auto" };
    if (form.environment === "Mobile") return { preset: "android_chromium" };
    if (form.environment === "Custom") {
      const payload = { preset: "custom", mobile_mode: Boolean(form.mobile_mode), touch_mode: Boolean(form.touch_mode) };
      if (form.language.trim()) payload.language = form.language.trim();
      if (form.timezone.trim()) payload.timezone = form.timezone.trim();
      if (form.user_agent.trim()) payload.user_agent = form.user_agent.trim();
      return payload;
    }
    return { preset: "desktop" };
  };

  const parseProxy = async () => {
    if (!form.proxy_input.trim()) return;
    try { const parsed = await call("parse_proxy", form.proxy_input); setProxyDirty(true); setProxyCredentialsDirty(Boolean(parsed.authenticated)); setForm((current) => ({ ...current, enabled: true, scheme: parsed.scheme, host: parsed.host, port: parsed.port, username: parsed.username || "", proxy_password: parsed.password || "", proxy_input: "" })); notify(parsed.authenticated ? "Đã đọc Proxy có xác thực; thông tin này chỉ được xuất khi bạn yêu cầu." : "Đã đọc địa chỉ Proxy."); }
    catch (error) { notify(userError(error), "error"); }
  };

  const generateEnvironment = async () => {
    if (!profile?.profile_id) return;
    setGenerating(true);
    try { const result = await call("generate_environment", profile.profile_id, form.environment); const saved = result?.profile || result; if (!saved?.environment) throw new Error("environment unavailable"); setEnvironmentMeta(saved.environment); setForm((current) => ({ ...current, environment: presetFor(saved.environment), ...environmentFields(saved.environment) })); onSaved(saved); notify("Đã tạo và lưu môi trường."); }
    catch (error) { notify(userError(error), "error"); } finally { setGenerating(false); }
  };

  const save = async () => {
    setBusy(true);
    try {
      let accountInput = null;
      if (accountMode === "fast" && form.fastInput.trim()) accountInput = form.fastInput.trim();
      else if (accountMode === "structured" && accountDirty && (form.email.trim() || form.password || form.totp_secret)) accountInput = { email: form.email.trim(), password: form.password, totp_secret: form.totp_secret };
      const proxyPayload = form.enabled ? { enabled: true, scheme: form.scheme, host: form.host, port: Number(form.port) } : { enabled: false };
      if (proxyCredentialsDirty && form.enabled) {
        proxyPayload.username = form.username;
        proxyPayload.password = form.proxy_password;
      }
      const nextEnvironment = profile ? (environmentDirty ? environmentPayload() : null) : environmentPayload();
      const nextProxy = profile ? (proxyDirty ? proxyPayload : null) : proxyPayload;
      const result = profile ? await call("update_profile", profile.profile_id, form.name, accountInput, false, nextEnvironment, nextProxy) : await call("create_profile", form.name || null, accountInput, nextEnvironment, nextProxy);
      onSaved(result); notify(profile ? "Đã cập nhật hồ sơ." : "Đã tạo hồ sơ với môi trường Auto."); closeDialog();
    } catch (error) { notify(userError(error), "error"); } finally { setBusy(false); }
  };

  const mobile = form.environment === "Mobile";
  const version = environmentMeta?.runtime_version || runtime?.browser_version || "không rõ";
  const closeFromBackdrop = (event) => { if (event.target === event.currentTarget) closeDialog(); };
  return <div className={backdropClassName} onMouseDown={closeFromBackdrop}><div ref={dialogRef} tabIndex={-1} className={`modal-card editor-modal ${dialogClassName}`} role="dialog" aria-modal="true" aria-labelledby="profile-editor-title">
    <div className="modal-heading"><div><p className="eyebrow">{profile ? "Chỉnh sửa hồ sơ" : "Hồ sơ mới"}</p><h2 id="profile-editor-title">{profile ? profile.name : "Tạo không gian độc lập"}</h2></div><button className="icon-button tooltip-trigger" onClick={closeDialog} aria-label="Đóng" data-tooltip="Đóng" title="Đóng"><X className="h-4 w-4" /></button></div>
    <div className="modal-tabs"><button className={`tab ${tab === "account" ? "tab-active" : ""}`} onClick={() => setTab("account")}><KeyRound className="h-4 w-4" />Tài khoản</button><button className={`tab ${tab === "runtime" ? "tab-active" : ""}`} onClick={() => setTab("runtime")}><Network className="h-4 w-4" />Môi trường / Proxy</button></div>
    <div className="editor-modal-body space-y-5 p-6">{tab === "account" ? <>
      <label className="field-label">Tên hiển thị<input className="control mt-2 w-full" placeholder="Mặc định lấy phần trước email" value={form.name} onChange={(event) => { setNameTouched(true); update("name", event.target.value); }} /></label>
      <div className="mode-switch"><button className={accountMode === "fast" ? "mode-active" : ""} onClick={() => setAccountMode("fast")}>Nhập nhanh</button><button className={accountMode === "structured" ? "mode-active" : ""} onClick={() => setAccountMode("structured")}>Nhập chi tiết</button></div>
      {accountMode === "fast" ? <label className="field-label">Dữ liệu tài khoản <span className="muted">email:password[:2fa]</span><input className="control mt-2 w-full" type="password" autoComplete="off" placeholder={profile ? "Để trống để giữ tài khoản hiện tại" : "email:password hoặc email:password:2fa"} value={form.fastInput} onChange={(event) => updateFast(event.target.value)} /></label> : <div className="space-y-3"><label className="field-label">Email<input className="control mt-2 w-full" type="email" autoComplete="off" value={form.email} onChange={(event) => updateEmail(event.target.value)} /></label><label className="field-label">Mật khẩu<input className="control mt-2 w-full" type="password" autoComplete="new-password" value={form.password} onChange={(event) => { setAccountDirty(true); update("password", event.target.value); }} /></label><label className="field-label">Mã TOTP <span className="muted">tùy chọn</span><input className="control mt-2 w-full" type="password" autoComplete="off" value={form.totp_secret} onChange={(event) => { setAccountDirty(true); update("totp_secret", event.target.value); }} /></label></div>}
      <p className="warning-box">Thông tin đăng nhập được giữ trong cấu hình Autofill riêng của hồ sơ. Tệp xuất tài khoản có thể chứa dữ liệu nhạy cảm; hãy lưu ở nơi an toàn.</p>
    </> : <>
      <label className="field-label">Preset môi trường<select className="control mt-2 w-full" value={form.environment} onChange={(event) => { setEnvironmentDirty(true); update("environment", event.target.value); }}><option>Auto</option><option>Desktop</option><option>Mobile</option><option>Custom</option></select></label>
      <p className="helper-copy">{form.environment === "Auto" ? "Auto để Chromium và Windows dùng hành vi mặc định, không thêm cấu hình môi trường riêng." : mobile ? "Mobile chỉ thay đổi thiết lập nhận dạng được Chromium hỗ trợ; cửa sổ vẫn phù hợp với Windows." : form.environment === "Custom" ? "Thiết lập tùy chỉnh được lưu dưới dạng metadata. Mobile và cảm ứng không mô phỏng đầy đủ thiết bị." : "Thiết lập Desktop chỉ áp dụng khi bạn chủ động chọn preset này."}</p>
      {form.environment === "Auto" ? <div className="settings-inset"><div className="inset-heading"><div><strong>Môi trường hồ sơ</strong><p>Preset: Auto · Chromium {version}</p></div><span className="info-chip">Mặc định</span></div><p className="helper-copy">Hồ sơ cũ có preset Generated vẫn được giữ nguyên trong catalog; giao diện hiển thị chúng là Auto để tương thích.</p></div> : <div className="settings-inset"><div className="inset-heading"><div><strong>Môi trường hồ sơ</strong><p>Preset: {form.environment} · Chromium {version}</p></div><span className="info-chip">Chỉ đọc</span></div><button className="secondary-button" disabled={!profile?.profile_id || generating} onClick={generateEnvironment}><RefreshCw className={generating ? "spin-once h-4 w-4" : "h-4 w-4"} />{generating ? "Đang tạo…" : "Tạo lại môi trường"}</button><div className="field-grid"><ReadField label="Chiều rộng cửa sổ" value={form.window_width} /><ReadField label="Chiều cao cửa sổ" value={form.window_height} /><label className="field-label field-span">Ngôn ngữ<input className="control mt-2 w-full" value={form.language} placeholder="Lấy từ Windows nếu có" onChange={(event) => updateEnvironment("language", event.target.value)} /></label><label className="field-label field-span">Múi giờ<input className="control mt-2 w-full" value={form.timezone} placeholder="Lấy từ Windows nếu có" onChange={(event) => updateEnvironment("timezone", event.target.value)} /></label><ReadField label="User-Agent đã tạo" value={form.user_agent} wide /><ReadField label="Khu vực Windows" value={form.region} wide /></div><p className="helper-copy">Ngôn ngữ, múi giờ và khu vực được giữ dưới dạng metadata nếu runtime không hỗ trợ áp dụng chúng.</p><div className="environment-notes"><span>Nhận dạng Mobile: {form.mobile_mode ? "Đã yêu cầu" : "Tắt"}</span><span>Chế độ cảm ứng: {form.touch_mode ? "Đã yêu cầu" : "Tắt"}</span></div></div>}
      <div className="settings-inset"><div className="inset-heading"><div><strong>Proxy</strong><p>Proxy không bắt buộc; để tắt, bỏ chọn công tắc.</p></div><button className={`toggle ${form.enabled ? "toggle-on" : ""}`} onClick={() => updateProxy("enabled", !form.enabled)} aria-label="Bật hoặc tắt Proxy" aria-pressed={form.enabled}><span /></button></div><p className="helper-copy">Thông tin đăng nhập Proxy được giữ trong cài đặt hồ sơ. Phiên bản này chưa áp dụng Proxy có xác thực cho Chromium.</p><div className="flex gap-2"><input className="control flex-1" placeholder="host:port hoặc http://user:password@host:port" value={form.proxy_input} onChange={(event) => updateProxy("proxy_input", event.target.value)} /><button className="secondary-button" onClick={parseProxy}>Đọc địa chỉ</button></div>{form.enabled && <div className="mt-3 grid grid-cols-3 gap-2"><select className="control" value={form.scheme} onChange={(event) => updateProxy("scheme", event.target.value)}><option value="http">HTTP</option><option value="https">HTTPS</option><option value="socks4">SOCKS4</option><option value="socks5">SOCKS5</option></select><input className="control col-span-2" placeholder="Máy chủ" value={form.host} onChange={(event) => updateProxy("host", event.target.value)} /><input className="control col-span-3" placeholder="Cổng" value={form.port} onChange={(event) => updateProxy("port", event.target.value)} /><input className="control col-span-3" placeholder="Tên đăng nhập Proxy (tùy chọn)" value={form.username} onChange={(event) => updateProxy("username", event.target.value)} /><input className="control col-span-3" type="password" placeholder="Mật khẩu Proxy (tùy chọn)" value={form.proxy_password} onChange={(event) => updateProxy("proxy_password", event.target.value)} /></div>}</div>
    </>}</div>
    <div className="modal-footer"><button className="secondary-button" onClick={closeDialog}>Hủy</button><button className="primary-button" onClick={save} disabled={busy || generating}>{busy ? "Đang lưu…" : <><Save className="h-4 w-4" />Lưu hồ sơ</>}</button></div>
  </div></div>;
}

function ReadField({ label, value, wide = false }) { return <label className={`field-label ${wide ? "field-span" : ""}`}>{label}<input className="control mt-2 w-full" value={value || ""} readOnly placeholder="Chưa có dữ liệu" /></label>; }
