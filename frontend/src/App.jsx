import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BridgeNotReadyError, call, hasNativeBridge, onBridgeReady } from "./api/bridge";
import Header from "./components/Header";
import ProfileTable from "./components/ProfileTable";
import RightSidebar from "./components/RightSidebar";
import Toasts from "./components/Toasts";
import ProfileEditorModal from "./dialogs/ProfileEditorModal";
import BatchImportDialog from "./dialogs/BatchImportDialog";
import ProxyCheckDialog from "./dialogs/ProxyCheckDialog";
import SettingsPage from "./pages/SettingsPage";
import AboutPage from "./pages/AboutPage";
import { applyProfileDeltaToRows } from "./profileDelta";
import { launchBatchOutcome, launchPollFailureState } from "./jobOutcome";
import { applyReduceMotionAttribute, normalizePreferences, readLocalPreferences, readLocalReduceMotionExplicit, resolveReduceMotionPreference, writeLocalPreferences } from "./uiPreferences";
import { UI, formatCount, userError } from "./i18n";

const DEMO_ROWS = [{
  profile_id: "profile_0001", stt: "0001", name: "Ví dụ", account: "demo@example.invalid",
  has_account: true, environment: { preset: "desktop", label: "Desktop" }, proxy: { enabled: false },
  status: "Closed", last_opened: null, created_at: null,
}];

function compareText(left, right) {
  return String(left || "").localeCompare(String(right || ""), undefined, { numeric: true, sensitivity: "base" });
}

function filterAndSortProfiles(rows, query, sort) {
  const needle = String(query || "").trim().toLocaleLowerCase();
  const filtered = rows.filter((row) => !needle || [row.stt, row.name, row.profile_id, row.account, row.status, row.proxy?.host].map((value) => String(value || "").toLocaleLowerCase()).some((value) => value.includes(needle)));
  if (sort === "last_opened") {
    const opened = filtered.filter((row) => row.last_opened).sort((left, right) => Date.parse(right.last_opened) - Date.parse(left.last_opened) || compareText(left.stt, right.stt));
    const unopened = filtered.filter((row) => !row.last_opened).sort((left, right) => compareText(left.stt, right.stt));
    return [...opened, ...unopened];
  }
  const values = { stt: (row) => row.stt, name: (row) => row.name, id: (row) => row.profile_id, status: (row) => row.status };
  const value = values[sort] || values.stt;
  return [...filtered].sort((left, right) => compareText(value(left), value(right)) || compareText(left.stt, right.stt));
}

export default function App() {
  const [profiles, setProfiles] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("stt");
  const [refreshing, setRefreshing] = useState(false);
  const [modal, setModal] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [runtime, setRuntime] = useState(null);
  const [bridgeReady, setBridgeReady] = useState(hasNativeBridge);
  const [delay, setDelay] = useState("2");
  const [batch, setBatch] = useState(null);
  const [deleteInFlight, setDeleteInFlight] = useState(false);
  const [preferences, setPreferences] = useState(readLocalPreferences);
  const [reduceMotionExplicit, setReduceMotionExplicit] = useState(readLocalReduceMotionExplicit);
  const reduceMotionExplicitRef = useRef(reduceMotionExplicit);
  reduceMotionExplicitRef.current = reduceMotionExplicit;
  const [osReduceMotion, setOsReduceMotion] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches || false);
  const lastErrorToast = useRef(null);

  const notify = useCallback((message, type = "success") => {
    const normalized = String(message || (type === "error" ? "Không thể hoàn tất thao tác." : "Đã hoàn tất."));
    const key = `${type}:${normalized}`;
    if (type === "error" && lastErrorToast.current === key) return;
    lastErrorToast.current = type === "error" ? key : null;
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((items) => [...items, { id, message: normalized, type }]);
  }, []);

  const updatePreferences = useCallback((changes) => {
    setPreferences((current) => normalizePreferences({ ...current, ...changes }));
  }, []);

  useEffect(() => {
    let active = true;
    const unsubscribe = onBridgeReady(() => {
      if (active) setBridgeReady(true);
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!bridgeReady) return undefined;
    let active = true;
    call("get_ui_preferences").then((saved) => {
      if (!active || !saved || !Object.keys(saved).length) return;
      const localChoice = reduceMotionExplicitRef.current ?? readLocalReduceMotionExplicit();
      setPreferences((current) => normalizePreferences({
        ...current,
        ...saved,
        reduce_motion: localChoice === null && saved.reduce_motion !== true ? current.reduce_motion : saved.reduce_motion,
      }));
      if (localChoice === null && saved.reduce_motion === true) setReduceMotionExplicit(true);
    }).catch(() => {});
    return () => { active = false; };
  }, [bridgeReady]);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = preferences.theme;
    root.style.colorScheme = preferences.theme;
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.content = getComputedStyle(root).getPropertyValue("--color-ink").trim();
  }, [preferences.theme]);

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setOsReduceMotion(Boolean(media?.matches));
    updateMotion();
    media?.addEventListener?.("change", updateMotion);
    return () => media?.removeEventListener?.("change", updateMotion);
  }, []);

  const effectiveReduceMotion = resolveReduceMotionPreference(reduceMotionExplicit, osReduceMotion);

  useEffect(() => {
    applyReduceMotionAttribute(document.documentElement, effectiveReduceMotion);
  }, [effectiveReduceMotion]);

  useEffect(() => {
    writeLocalPreferences(preferences, reduceMotionExplicit);
    const timer = bridgeReady
      ? window.setTimeout(() => call("save_ui_preferences", preferences).catch(() => {}), 120)
      : null;
    return () => { if (timer !== null) window.clearTimeout(timer); };
  }, [bridgeReady, preferences, reduceMotionExplicit]);

  const loadProfiles = useCallback(async () => {
    setRefreshing(true);
    try {
      const rows = await call("list_profiles", "", "stt", false);
      setProfiles(rows);
      setSelected((current) => new Set([...current].filter((id) => rows.some((row) => row.profile_id === id))));
    } catch (error) {
      if (!(error instanceof BridgeNotReadyError)) notify(userError(error), "error");
    } finally { setRefreshing(false); }
  }, [notify]);

  const applyProfileDelta = useCallback((updates = [], removedIds = []) => {
    if (!Array.isArray(updates) || !updates.every((row) => row && typeof row.profile_id === "string" && typeof row.name === "string")) return false;
    const removals = new Set((Array.isArray(removedIds) ? removedIds : []).map(String));
    setProfiles((current) => applyProfileDeltaToRows(current, updates, removedIds));
    if (removals.size) setSelected((current) => new Set([...current].filter((id) => !removals.has(id))));
    return true;
  }, []);

  const handleProfileSaved = useCallback((row) => {
    if (!applyProfileDelta([row])) notify("Đã lưu hồ sơ nhưng bảng chưa thể cập nhật. Hãy bấm Làm mới để đồng bộ lại.", "error");
    else notify("Đã lưu thay đổi hồ sơ.");
  }, [applyProfileDelta, notify]);

  const handleImportDone = useCallback((result) => {
    const rows = Array.isArray(result?.profiles) ? result.profiles : [];
    const created = Number(result?.created || 0);
    if (created && rows.length !== created) notify("Đã nhập nhưng bảng nhận được dữ liệu chưa đầy đủ. Hãy bấm Làm mới.", "error");
    if (rows.length && !applyProfileDelta(rows)) notify("Đã nhập nhưng bảng chưa thể cập nhật. Hãy bấm Làm mới.", "error");
    if (created && rows.length === created) notify(`Đã tạo ${created} hồ sơ từ dữ liệu nhập.`);
  }, [applyProfileDelta, notify]);

  useEffect(() => {
    if (bridgeReady) {
      loadProfiles();
      return undefined;
    }
    if (import.meta.env.DEV && !hasNativeBridge()) setProfiles(DEMO_ROWS);
    return undefined;
  }, [bridgeReady, loadProfiles]);

  useEffect(() => {
    if (!bridgeReady) return undefined;
    let active = true;
    const pollStatus = async () => {
      if (!hasNativeBridge()) return;
      try {
        const updates = await call("refresh_status");
        if (!active || !Array.isArray(updates)) return;
        const statusById = new Map(updates.map((item) => [item.profile_id, item.status]));
        setProfiles((current) => { let changed = false; const next = current.map((row) => { const status = statusById.get(row.profile_id); if (!status || status === row.status) return row; changed = true; return { ...row, status }; }); return changed ? next : current; });
      } catch { /* Status is best-effort and should never interrupt the table. */ }
    };
    const timer = window.setInterval(pollStatus, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [bridgeReady]);

  useEffect(() => {
    if (bridgeReady) call("get_runtime_info").then(setRuntime).catch(() => {});
  }, [bridgeReady]);

  const visibleProfiles = useMemo(() => filterAndSortProfiles(profiles, query, sort), [profiles, query, sort]);
  const selectedRows = useMemo(() => profiles.filter((row) => selected.has(row.profile_id)), [profiles, selected]);
  const selectedProfile = selectedRows.length === 1 ? selectedRows[0] : null;
  const toggle = (id) => setSelected((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const toggleAll = () => setSelected((current) => visibleProfiles.length > 0 && visibleProfiles.every((row) => current.has(row.profile_id)) ? new Set([...current].filter((id) => !visibleProfiles.some((row) => row.profile_id === id))) : new Set([...current, ...visibleProfiles.map((row) => row.profile_id)]));

  const exportAccountData = async (kind) => {
    try {
      if (!selected.size) { notify("Hãy chọn ít nhất một hồ sơ trước khi xuất dữ liệu.", "error"); return; }
      const result = await call("save_account_export", kind, [...selected]);
      if (result?.cancelled) { notify("Đã hủy xuất dữ liệu."); return; }
      if (!result?.saved) throw new Error("export failed");
      notify(`Đã lưu tệp ${kind.toUpperCase()}${result.filename ? `: ${result.filename}` : ""}.`);
    } catch (error) { notify(userError(error), "error"); }
  };

  const launch = async () => {
    try { const jobId = await call("launch_batch", [...selected], Number(delay)); setBatch({ jobId, status: "running", progress: { completed: 0, total: selected.size }, onCancel: () => call("cancel_batch", jobId) }); }
    catch (error) { notify(userError(error), "error"); }
  };

  const launchOne = async (row) => {
    try { const result = await call("launch_profile", row.profile_id); if (result?.profile) applyProfileDelta([result.profile]); notify(result?.already_running ? "Hồ sơ đang mở." : "Đã mở hồ sơ."); }
    catch (error) { notify(userError(error), "error"); }
  };

  useEffect(() => {
    if (!batch?.jobId) return undefined;
    let inFlight = false;
    let terminal = false;
    const timer = window.setInterval(async () => {
      if (inFlight || terminal) return;
      inFlight = true;
      try {
        const state = await call("get_job", batch.jobId);
        if (terminal) return;
        const displayState = state.status === "completed" && Number(state.result?.failed || 0) > 0
          ? { ...state, status: "failed" }
          : state;
        setBatch((current) => ({ ...current, ...displayState, onCancel: current?.onCancel }));
        if (["completed", "failed", "cancelled"].includes(state.status)) {
          terminal = true;
          window.clearInterval(timer);
          if (state.status === "completed" || state.status === "failed") {
            const outcome = launchBatchOutcome(state);
            notify(outcome.message, outcome.type);
          }
          if (state.result?.profiles?.length) applyProfileDelta(state.result.profiles);
        }
      } catch (error) {
        if (terminal) return;
        terminal = true;
        window.clearInterval(timer);
        setBatch((current) => launchPollFailureState(current, batch.jobId));
        notify(userError(error, "Không thể kiểm tra tiến trình mở hồ sơ. Hãy làm mới danh sách để kiểm tra kết quả."), "error");
      } finally {
        inFlight = false;
      }
    }, 300);
    return () => {
      terminal = true;
      window.clearInterval(timer);
    };
  }, [applyProfileDelta, batch?.jobId, notify]);

  const deleteSelected = async () => {
    if (deleteInFlight || !selected.size) return;
    const profileIds = [...selected];
    if (!window.confirm(`Bạn có chắc muốn xóa ${profileIds.length} hồ sơ đã chọn? Dữ liệu trình duyệt độc lập của các hồ sơ này cũng sẽ bị xóa.`)) return;
    setDeleteInFlight(true);
    try {
      const result = await call("delete_profiles", profileIds, true);
      const deletedIds = Array.isArray(result.deleted_profile_ids) ? result.deleted_profile_ids : (result.results || []).filter((item) => item.status === "deleted").map((item) => item.profile_id);
      notify(`Đã xóa ${result.deleted || 0} hồ sơ${result.failed ? `; ${result.failed} hồ sơ thất bại` : ""}.`, result.failed ? "error" : "success");
      if (Number(result.deleted || 0) !== deletedIds.length || !applyProfileDelta([], deletedIds)) notify("Đã xóa nhưng bảng chưa thể cập nhật đầy đủ. Hãy bấm Làm mới.", "error");
    } catch (error) { notify(userError(error), "error"); } finally { setDeleteInFlight(false); }
  };

  const chooseTheme = (theme) => updatePreferences({ theme });
  const updateSettingPreferences = useCallback((changes) => {
    updatePreferences(changes);
    if (Object.hasOwn(changes, "reduce_motion")) {
      const choice = Boolean(changes.reduce_motion);
      reduceMotionExplicitRef.current = choice;
      setReduceMotionExplicit(choice);
    }
  }, [updatePreferences]);

  return <div className="app-shell">
    <Header query={query} onQuery={setQuery} sort={sort} onSort={setSort} onRefresh={loadProfiles} refreshing={refreshing} theme={preferences.theme} onThemeChange={chooseTheme} onSettings={() => setModal({ type: "settings" })} onAbout={() => setModal({ type: "about" })} />
    <main className="app-main"><div className="dashboard-content"><ProfileTable rows={visibleProfiles} selected={selected} onToggle={toggle} onToggleAll={toggleAll} onEdit={(row) => setModal({ type: "edit", profile: row })} onOpen={launchOne} visibleColumns={preferences.visible_columns} /><div className="workspace-strip"><div><p className="eyebrow">Hồ sơ đang chọn</p><p className="workspace-name">{selectedProfile ? `${selectedProfile.stt} · ${selectedProfile.name}` : "Chọn một hồ sơ để xem thông tin nhanh"}</p></div>{runtime && <p className={runtime.browser_available ? "runtime-inline runtime-ready" : "runtime-inline runtime-warning"}>{runtime.browser_available ? "Runtime sẵn sàng" : "Thiếu browser/chrome.exe"}</p>}</div></div><RightSidebar selectedCount={selected.size} delay={delay} onDelay={setDelay} onLaunch={launch} onCreate={() => setModal({ type: "create" })} onImport={() => setModal({ type: "import" })} onExport={exportAccountData} onEdit={() => selectedProfile && setModal({ type: "edit", profile: selectedProfile })} onDelete={deleteSelected} deleteInFlight={deleteInFlight} onClear={() => setSelected(new Set())} onCheckProxy={() => setModal({ type: "check", profile: selectedProfile })} batch={batch} profileCount={profiles.length} runningCount={profiles.filter((row) => row.status === "Running").length} proxyCount={profiles.filter((row) => row.proxy?.enabled).length} /></main>
    {modal?.type === "settings" && <SettingsPage preferences={{ ...preferences, reduce_motion: effectiveReduceMotion }} onPreferenceChange={updateSettingPreferences} notify={notify} onClose={() => setModal(null)} />}
    {modal?.type === "about" && <AboutPage notify={notify} onClose={() => setModal(null)} />}
    {(modal?.type === "create" || modal?.type === "edit") && <ProfileEditorModal profile={modal.profile} onClose={() => setModal(null)} onSaved={handleProfileSaved} notify={notify} />}
    {modal?.type === "import" && <BatchImportDialog onClose={() => setModal(null)} onDone={handleImportDone} notify={notify} />}
    {modal?.type === "check" && <ProxyCheckDialog profile={modal.profile} onClose={() => setModal(null)} notify={notify} />}
    <Toasts items={toasts} onDismiss={(id) => setToasts((items) => items.filter((item) => item.id !== id))} />
  </div>;
}
