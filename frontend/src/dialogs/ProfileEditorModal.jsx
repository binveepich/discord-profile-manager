import { useEffect, useState } from "react";
import { KeyRound, Network, RefreshCw, Save, X } from "lucide-react";
import { call } from "../api/bridge";

const EMPTY_ENVIRONMENT = {
  window_width: "",
  window_height: "",
  language: "",
  language_order: "",
  region: "",
  timezone: "",
  user_agent: "",
  mobile_mode: false,
  touch_mode: false,
};

const SOURCE_LABELS = {
  "windows-system-derived": "Windows-system-derived",
  windows_system_derived: "Windows-system-derived",
  windows_system: "Windows-system-derived",
  system: "Windows-system-derived",
  generated: "Generated",
  applied: "Applied to Chromium",
  chromium: "Applied to Chromium",
  "applied-to-chromium": "Applied to Chromium",
  metadata: "Metadata only",
  metadata_only: "Metadata only",
  "metadata-only": "Metadata only",
  unsupported: "Unsupported",
};

function displayNameFromEmail(email) {
  return String(email || "").split("@", 1)[0].replace(/[<>:/\\|?*\x00-\x1f]/g, "").trim();
}

function editorPreset(environment) {
  const preset = String(environment?.preset || "").toLowerCase();
  if (preset === "android_chromium" || preset === "mobile") return "Mobile";
  if (preset === "custom") return "Custom";
  // Generated profiles can preserve their generated storage preset while the
  // selected family remains available through the DTO when provided.
  const generatedFamily = String(environment?.generated_family || environment?.generator_preset || "").toLowerCase();
  if (preset === "generated" && (generatedFamily.includes("android") || generatedFamily.includes("mobile"))) return "Mobile";
  return "Desktop";
}

function fieldsFromEnvironment(environment) {
  return {
    window_width: environment?.window_width ?? environment?.viewport_width ?? environment?.window_geometry?.width ?? "",
    window_height: environment?.window_height ?? environment?.viewport_height ?? environment?.window_geometry?.height ?? "",
    language: environment?.language ?? "",
    language_order: Array.isArray(environment?.language_order)
      ? environment.language_order.join(", ")
      : environment?.language_order ?? "",
    region: environment?.region ?? "",
    timezone: environment?.timezone ?? "",
    user_agent: environment?.user_agent ?? "",
    mobile_mode: Boolean(environment?.mobile_mode),
    touch_mode: Boolean(environment?.touch_mode),
  };
}

function normalizeSourceLabel(value) {
  const key = value.trim().toLowerCase().replace(/\s+/g, "-");
  if (SOURCE_LABELS[key]) return SOURCE_LABELS[key];
  if (key.startsWith("windows-system-derived")) return "Windows-system-derived";
  if (key.startsWith("generated")) return "Generated";
  if (key.startsWith("applied")) return "Applied to Chromium";
  if (key.startsWith("metadata")) return "Metadata only";
  if (key.startsWith("unsupported")) return "Unsupported";
  return value.trim();
}

function sourceMetadata(environment, field) {
  const aliases = {
    window_width: ["window_width", "viewport_width", "window_geometry"],
    window_height: ["window_height", "viewport_height", "window_geometry"],
    language: ["language", "locale"],
    language_order: ["language_order", "languages", "locale"],
    region: ["region", "windows_region"],
    timezone: ["timezone"],
    user_agent: ["user_agent", "ua"],
    mobile_mode: ["mobile_mode", "mobile"],
    touch_mode: ["touch_mode", "touch"],
  };
  const keys = aliases[field] || [field];
  const containers = [
    environment?.field_metadata,
    environment?.field_sources,
    environment?.sources,
    environment?.metadata,
  ];
  for (const container of containers) {
    if (!container || typeof container !== "object") continue;
    for (const key of keys) {
      if (container[key] !== undefined) return container[key];
    }
  }
  return null;
}

function sourceLabels(environment, field, fallback = []) {
  const metadata = sourceMetadata(environment, field);
  const raw = typeof metadata === "string"
    ? [metadata]
    : Array.isArray(metadata)
      ? metadata
      : metadata && typeof metadata === "object"
        ? [
          metadata.source,
          metadata.value_source,
          metadata.origin,
          metadata.application,
          metadata.apply,
          metadata.status,
        ]
        : [];
  const labels = raw
    .flatMap((value) => Array.isArray(value) ? value : [value])
    .flatMap((value) => typeof value === "string" ? value.split(/[;,]/) : [value])
    .filter((value) => typeof value === "string" && value.trim())
    .map(normalizeSourceLabel);
  return [...new Set(labels.length ? labels : fallback)];
}

function sourceTone(label) {
  if (label === "Applied to Chromium") return "environment-source environment-source-applied";
  if (label === "Metadata only") return "environment-source environment-source-metadata";
  if (label === "Unsupported") return "environment-source environment-source-unsupported";
  if (label === "Windows-system-derived") return "environment-source environment-source-system";
  return "environment-source environment-source-generated";
}

function SourceLabels({ environment, field, fallback }) {
  const labels = sourceLabels(environment, field, fallback);
  if (!labels.length) return null;
  return <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">{labels.map((label) => <span className={sourceTone(label)} key={label}>{label}</span>)}</span>;
}

function optionalInteger(value) {
  const text = String(value ?? "").trim();
  return /^\d+$/.test(text) ? Number(text) : undefined;
}

function customEnvironmentPayload(form) {
  const payload = { preset: "custom" };
  if (form.language.trim()) payload.language = form.language.trim();
  if (form.timezone.trim()) payload.timezone = form.timezone.trim();
  if (form.user_agent.trim()) payload.user_agent = form.user_agent.trim();
  payload.mobile_mode = Boolean(form.mobile_mode);
  payload.touch_mode = Boolean(form.touch_mode);
  return payload;
}

function environmentPayload(form) {
  if (form.environment === "Mobile") return { preset: "android_chromium" };
  if (form.environment === "Custom") return customEnvironmentPayload(form);
  return { preset: "desktop" };
}

export default function ProfileEditorModal({ profile, onClose, onSaved, notify }) {
  const existingEnvironment = profile?.environment || {};
  const [tab, setTab] = useState("account");
  const [accountMode, setAccountMode] = useState("fast");
  const [nameTouched, setNameTouched] = useState(Boolean(profile));
  const [runtime, setRuntime] = useState(null);
  const [environmentMeta, setEnvironmentMeta] = useState(existingEnvironment);
  const [form, setForm] = useState({
    name: profile?.name || "",
    fastInput: "",
    email: profile?.account || "",
    password: "",
    totp_secret: "",
    environment: editorPreset(existingEnvironment),
    enabled: Boolean(profile?.proxy?.enabled),
    scheme: profile?.proxy?.scheme || "http",
    host: profile?.proxy?.host || "",
    port: profile?.proxy?.port || "",
    username: "",
    proxy_password: "",
    ...EMPTY_ENVIRONMENT,
    ...fieldsFromEnvironment(existingEnvironment),
    proxy_input: "",
  });
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    call("get_runtime_info").then(setRuntime).catch(() => {});
  }, []);

  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const updateEmail = (value) => setForm((current) => ({
    ...current,
    email: value,
    name: !nameTouched ? displayNameFromEmail(value) : current.name,
  }));
  const updateFastInput = (value) => setForm((current) => ({
    ...current,
    fastInput: value,
    name: !nameTouched ? displayNameFromEmail(value.split(":", 1)[0]) : current.name,
  }));
  const updateEnvironmentField = (key, value) => setForm((current) => ({
    ...current,
    // Direct edits are local until Save. They make only this profile Custom
    // and never trigger an implicit regeneration.
    environment: "Custom",
    [key]: value,
  }));
  const selectPreset = (value) => update("environment", value);

  const parseProxy = async () => {
    if (!form.proxy_input.trim()) return;
    try {
      const parsed = await call("parse_proxy", form.proxy_input);
      setForm((current) => ({ ...current, enabled: true, scheme: parsed.scheme, host: parsed.host, port: parsed.port, username: parsed.username || "", proxy_password: parsed.password || "", proxy_input: "" }));
      notify(parsed.authenticated ? "Authenticated proxy parsed. Credentials will be included only in explicit account exports." : "Proxy parsed.", "success");
    } catch (error) { notify(error.message, "error"); }
  };

  const generateEnvironment = async () => {
    if (!profile?.profile_id) return;
    setGenerating(true);
    try {
      const result = await call("generate_environment", profile.profile_id, form.environment);
      const savedProfile = result?.profile || result;
      const savedEnvironment = savedProfile?.environment;
      if (!savedEnvironment || typeof savedEnvironment !== "object") {
        throw new Error("The environment generator did not return the saved profile.");
      }
      // Values update only after the bridge confirms the generated state was
      // persisted. Ordinary profile refreshes never execute this operation.
      setEnvironmentMeta(savedEnvironment);
      setForm((current) => ({
        ...current,
        environment: editorPreset(savedEnvironment),
        ...fieldsFromEnvironment(savedEnvironment),
      }));
      onSaved(savedProfile);
      notify("Environment generated and saved.");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setGenerating(false);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      let accountInput = null;
      if (accountMode === "fast" && form.fastInput.trim()) {
        accountInput = form.fastInput.trim();
      } else if (accountMode === "structured" && (form.email.trim() || form.password || form.totp_secret)) {
        accountInput = {
          email: form.email.trim(),
          password: form.password,
          totp_secret: form.totp_secret,
        };
      }
      const proxyPayload = form.enabled ? { enabled: true, scheme: form.scheme, host: form.host, port: Number(form.port), username: form.username || undefined, password: form.proxy_password || undefined } : { enabled: false };
      const result = profile
        ? await call("update_profile", profile.profile_id, form.name, accountInput, false, environmentPayload(form), proxyPayload)
        : await call("create_profile", form.name || null, accountInput, environmentPayload(form), proxyPayload);
      notify(profile ? "Profile updated." : "Profile created with a saved environment.");
      onSaved(result);
      onClose();
    } catch (error) { notify(error.message, "error"); } finally { setBusy(false); }
  };

  const runtimeVersion = environmentMeta?.runtime_version || runtime?.browser_version || "Runtime version unavailable";
  const isMobile = form.environment === "Mobile";

  return <div className="modal-backdrop"><div className="modal-card editor-modal">
    <div className="flex flex-none items-start justify-between border-b border-line px-6 py-5"><div><p className="eyebrow">{profile ? "Edit profile" : "New profile"}</p><h2 className="mt-1 text-lg font-semibold text-white">{profile ? profile.name : "Create an isolated workspace"}</h2></div><button className="icon-button" onClick={onClose}><X className="h-4 w-4" /></button></div>
    <div className="flex flex-none border-b border-line px-6"><button className={`tab ${tab === "account" ? "tab-active" : ""}`} onClick={() => setTab("account")}><KeyRound className="h-4 w-4" />Account</button><button className={`tab ${tab === "runtime" ? "tab-active" : ""}`} onClick={() => setTab("runtime")}><Network className="h-4 w-4" />Environment / Proxy</button></div>
    <div className="editor-modal-body space-y-5 p-6">{tab === "account" ? <>
      <label className="field-label">Display name<input className="control mt-2 w-full" placeholder="Defaults to the email prefix" value={form.name} onChange={(event) => { setNameTouched(true); update("name", event.target.value); }} /></label>
      <div className="flex gap-2 rounded-lg border border-line bg-elevated/60 p-1"><button className={`flex-1 rounded-md px-3 py-2 text-xs ${accountMode === "fast" ? "bg-accent text-white" : "text-slate-400"}`} onClick={() => setAccountMode("fast")}>Fast input</button><button className={`flex-1 rounded-md px-3 py-2 text-xs ${accountMode === "structured" ? "bg-accent text-white" : "text-slate-400"}`} onClick={() => setAccountMode("structured")}>Structured</button></div>
      {accountMode === "fast" ? <label className="field-label">Account input<span className="ml-2 text-slate-600">email:password[:2fa]</span><input className="control mt-2 w-full" type="password" autoComplete="off" placeholder={profile ? "Leave blank to keep the current account" : "email:password or email:password:2fa"} value={form.fastInput} onChange={(event) => updateFastInput(event.target.value)} /></label> : <div className="space-y-3"><label className="field-label">Email<input className="control mt-2 w-full" type="email" autoComplete="off" value={form.email} onChange={(event) => updateEmail(event.target.value)} /></label><label className="field-label">Password<input className="control mt-2 w-full" type="password" autoComplete="new-password" value={form.password} onChange={(event) => update("password", event.target.value)} /></label><label className="field-label">TOTP secret <span className="text-slate-600">optional</span><input className="control mt-2 w-full" type="password" autoComplete="off" value={form.totp_secret} onChange={(event) => update("totp_secret", event.target.value)} /></label></div>}
      <p className="rounded-lg border border-amber-400/20 bg-amber-400/5 p-3 text-xs leading-5 text-amber-200/80">Credentials are kept in the profile-local Autofill configuration. Export Account Data includes passwords, TOTP secrets, tokens if stored, and proxy credentials; store exported files securely.</p>
    </> : <>
      <div><label className="field-label">Environment preset<select className="control mt-2 w-full" value={form.environment} onChange={(event) => selectPreset(event.target.value)}><option>Desktop</option><option>Mobile</option><option>Custom</option></select></label><p className="mt-2 text-xs leading-5 text-slate-500">{isMobile ? "Mobile changes only supported Chromium identity settings. The physical Chromium window still uses a desktop-usable Windows work-area layout; it does not become a phone-sized window." : form.environment === "Custom" ? "Direct field edits stay local until Save and make only this profile Custom." : "Environment values are generated and persisted for this profile; refreshing the manager does not regenerate them."}</p></div>
      <div className="rounded-lg border border-line bg-elevated/60 p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium text-slate-200">Profile environment</p><p className="mt-1 text-xs text-slate-500">Current preset: {environmentMeta?.label || existingEnvironment?.label || form.environment} · Chromium {runtimeVersion}</p></div><span className="rounded-full bg-accent/15 px-2 py-1 text-[10px] text-accent">Runtime version read-only</span></div><div className="mt-3 flex flex-wrap items-center gap-2"><button className="secondary-button" disabled={!profile?.profile_id || generating} onClick={generateEnvironment}><RefreshCw className={`h-3.5 w-3.5 ${generating ? "animate-spin" : ""}`} />{generating ? "Generating..." : profile ? "Regenerate Environment" : "Generate Environment"}</button>{!profile && <span className="text-xs text-slate-500">The initial environment is generated and saved when this profile is created.</span>}</div>
        <div className="mt-4 grid grid-cols-2 gap-3"><label className="field-label">Physical window width<SourceLabels environment={environmentMeta} field="window_width" fallback={form.window_width ? ["Generated"] : []} /><input className="control mt-2 w-full" value={form.window_width} readOnly /></label><label className="field-label">Physical window height<SourceLabels environment={environmentMeta} field="window_height" fallback={form.window_height ? ["Generated"] : []} /><input className="control mt-2 w-full" value={form.window_height} readOnly /></label><label className="field-label col-span-2">Language<SourceLabels environment={environmentMeta} field="language" fallback={form.language ? ["Generated"] : []} /><input className="control mt-2 w-full" placeholder="Generated from Windows when available" value={form.language} onChange={(event) => updateEnvironmentField("language", event.target.value)} /></label><label className="field-label col-span-2">Timezone<SourceLabels environment={environmentMeta} field="timezone" fallback={form.timezone ? ["Metadata only"] : []} /><input className="control mt-2 w-full" placeholder="Generated from Windows when available" value={form.timezone} onChange={(event) => updateEnvironmentField("timezone", event.target.value)} /></label><label className="field-label col-span-2">Generated User-Agent<SourceLabels environment={environmentMeta} field="user_agent" fallback={form.user_agent ? ["Generated"] : []} /><input className="control mt-2 w-full text-xs" value={form.user_agent} placeholder="Generated by the backend" readOnly /></label></div>
        <div className="mt-3"><label className="field-label">Windows region<SourceLabels environment={environmentMeta} field="region" fallback={form.region ? ["Windows-system-derived"] : []} /><input className="control mt-2 w-full" value={form.region} placeholder="Reported by Windows when available" readOnly /></label></div>
        <div className="mt-3 space-y-2 text-xs"><div className="flex items-start justify-between gap-3"><span className="text-slate-400">Preferred language order</span><span className="max-w-[62%] text-right text-slate-300">{form.language_order || "Not recorded"}<SourceLabels environment={environmentMeta} field="language_order" fallback={form.language_order ? ["Windows-system-derived"] : []} /></span></div>{environmentMeta?.signature && <div className="flex items-center justify-between gap-3"><span className="text-slate-400">Environment signature</span><span className="font-mono text-[10px] text-slate-500">{environmentMeta.signature}</span></div>}</div>
        <div className="mt-4 space-y-2 border-t border-line pt-3 text-xs"><div className="flex items-center justify-between gap-3"><span className="text-slate-400">Mobile identity</span><span className="text-slate-300">{form.mobile_mode ? "Requested" : "Off"}<SourceLabels environment={environmentMeta} field="mobile_mode" fallback={form.mobile_mode ? ["Unsupported"] : []} /></span></div><div className="flex items-center justify-between gap-3"><span className="text-slate-400">Touch mode</span><span className="text-slate-300">{form.touch_mode ? "Requested" : "Off"}<SourceLabels environment={environmentMeta} field="touch_mode" fallback={form.touch_mode ? ["Generated"] : []} /></span></div></div>
      </div>
      <div className="rounded-lg border border-line bg-elevated/60 p-4"><div className="mb-3 flex items-center justify-between"><div><p className="text-sm font-medium text-slate-200">Proxy</p><p className="mt-1 text-xs text-slate-500">Credentials are optional and appear only in explicit account exports.</p></div><button className={`toggle ${form.enabled ? "toggle-on" : ""}`} onClick={() => update("enabled", !form.enabled)} aria-label="Toggle proxy"><span /></button></div><div className="flex gap-2"><input className="control flex-1" placeholder="host:port or http://user:password@host:port" value={form.proxy_input} onChange={(event) => update("proxy_input", event.target.value)} /><button className="secondary-button" onClick={parseProxy}>Parse</button></div>{form.enabled && <div className="mt-3 grid grid-cols-3 gap-2"><select className="control" value={form.scheme} onChange={(event) => update("scheme", event.target.value)}><option value="http">HTTP</option><option value="https">HTTPS</option><option value="socks4">SOCKS4</option><option value="socks5">SOCKS5</option></select><input className="control col-span-2" placeholder="Host" value={form.host} onChange={(event) => update("host", event.target.value)} /><input className="control col-span-3" placeholder="Port" value={form.port} onChange={(event) => update("port", event.target.value)} /><input className="control col-span-3" placeholder="Proxy username (optional)" value={form.username} onChange={(event) => update("username", event.target.value)} /><input className="control col-span-3" type="password" placeholder="Proxy password (optional)" value={form.proxy_password} onChange={(event) => update("proxy_password", event.target.value)} /></div>}</div>
    </>}</div>
    <div className="flex flex-none items-center justify-end gap-2 border-t border-line px-6 py-4"><button className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" onClick={save} disabled={busy || generating}>{busy ? "Saving..." : <><Save className="h-4 w-4" />Save profile</>}</button></div>
  </div></div>;
}
