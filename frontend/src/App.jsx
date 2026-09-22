import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Globe2, ShieldCheck } from "lucide-react";
import { call, hasNativeBridge, waitForBridge } from "./api/bridge";
import Header from "./components/Header";
import ProfileTable from "./components/ProfileTable";
import RightSidebar from "./components/RightSidebar";
import Toasts from "./components/Toasts";
import ProfileEditorModal from "./dialogs/ProfileEditorModal";
import BatchImportDialog from "./dialogs/BatchImportDialog";
import ProxyCheckDialog from "./dialogs/ProxyCheckDialog";
import { applyProfileDeltaToRows } from "./profileDelta";

const DEMO_ROWS = [{
  profile_id: "profile_0001",
  stt: "0001",
  name: "Work",
  account: "work@example.com",
  has_account: true,
  environment: { preset: "desktop", label: "Desktop" },
  proxy: { enabled: false },
  status: "Closed",
  last_opened: null,
  created_at: null,
}];

function compareText(left, right) {
  return String(left || "").localeCompare(String(right || ""), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function filterAndSortProfiles(rows, query, sort) {
  const needle = String(query || "").trim().toLocaleLowerCase();
  const filtered = rows.filter((row) => {
    if (!needle) return true;
    const searchable = [
      row.stt,
      row.name,
      row.profile_id,
      row.account,
      row.status,
      row.proxy?.host,
    ].map((value) => String(value || "").toLocaleLowerCase());
    return searchable.some((value) => value.includes(needle));
  });

  if (sort === "last_opened") {
    const opened = filtered.filter((row) => row.last_opened);
    const unopened = filtered.filter((row) => !row.last_opened);
    opened.sort((left, right) => (
      Date.parse(right.last_opened) - Date.parse(left.last_opened)
      || compareText(left.stt, right.stt)
    ));
    unopened.sort((left, right) => compareText(left.stt, right.stt));
    return [...opened, ...unopened];
  }

  const values = {
    stt: (row) => row.stt,
    name: (row) => row.name,
    id: (row) => row.profile_id,
    status: (row) => row.status,
  };
  const value = values[sort] || values.stt;
  return [...filtered].sort((left, right) => (
    compareText(value(left), value(right)) || compareText(left.stt, right.stt)
  ));
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
  const [delay, setDelay] = useState("2");
  const [batch, setBatch] = useState(null);
  const [deleteInFlight, setDeleteInFlight] = useState(false);
  const lastErrorToast = useRef(null);

  const notify = useCallback((message, type = "success") => {
    const normalized = String(message || "Operation failed.");
    const key = `${type}:${normalized}`;
    if (type === "error" && lastErrorToast.current === key) return;
    lastErrorToast.current = type === "error" ? key : null;
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((items) => [...items, { id, message: normalized, type }]);
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 4500);
  }, []);

  const loadProfiles = useCallback(async () => {
    setRefreshing(true);
    try {
      // Search and sorting are intentionally local. Full reads are reserved
      // for startup, manual Refresh, and recovery from an untrusted delta.
      const rows = await call("list_profiles", "", "stt", false);
      setProfiles(rows);
      setSelected((current) => new Set(
        [...current].filter((id) => rows.some((row) => row.profile_id === id)),
      ));
    } catch (error) {
      if (!hasNativeBridge()) setProfiles(DEMO_ROWS);
      else notify(error.message, "error");
    } finally {
      setRefreshing(false);
    }
  }, [notify]);

  const applyProfileDelta = useCallback((updates = [], removedIds = []) => {
    if (!Array.isArray(updates) || !updates.every((row) => (
      row && typeof row.profile_id === "string" && typeof row.name === "string"
    ))) return false;
    const removals = new Set((Array.isArray(removedIds) ? removedIds : []).map(String));
    setProfiles((current) => {
      const next = applyProfileDeltaToRows(current, updates, removedIds);
      return next;
    });
    if (removals.size) {
      setSelected((current) => new Set([...current].filter((id) => !removals.has(id))));
    }
    return true;
  }, []);

  const handleProfileSaved = useCallback((row) => {
    if (!applyProfileDelta([row])) {
      notify("Profile saved, but the table could not apply the returned profile summary. Use Refresh to resynchronize.", "error");
    }
  }, [applyProfileDelta, notify]);

  const handleImportDone = useCallback((result) => {
    const rows = Array.isArray(result?.profiles) ? result.profiles : [];
    const created = Number(result?.created || 0);
    if (created && rows.length !== created) {
      notify("Import succeeded, but the table received an incomplete profile delta. Use Refresh to resynchronize.", "error");
    }
    if (rows.length && !applyProfileDelta(rows)) {
      notify("Import succeeded, but the table could not apply the returned profile summaries. Use Refresh to resynchronize.", "error");
    }
  }, [applyProfileDelta, notify]);

  useEffect(() => {
    let active = true;
    waitForBridge().then(() => {
      if (active) loadProfiles();
    });
    return () => { active = false; };
  }, [loadProfiles]);

  useEffect(() => {
    let active = true;
    const pollStatus = async () => {
      if (!hasNativeBridge()) return;
      try {
        const updates = await call("refresh_status");
        if (!active || !Array.isArray(updates)) return;
        const statusById = new Map(updates.map((item) => [item.profile_id, item.status]));
        setProfiles((current) => {
          let changed = false;
          const next = current.map((row) => {
            const status = statusById.get(row.profile_id);
            if (!status || status === row.status) return row;
            changed = true;
            return { ...row, status };
          });
          return changed ? next : current;
        });
      } catch {
        // A transient process enumeration failure should not disrupt the table.
      }
    };
    const timer = window.setInterval(pollStatus, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    call("get_runtime_info").then(setRuntime).catch(() => {});
  }, []);

  const visibleProfiles = useMemo(
    () => filterAndSortProfiles(profiles, query, sort),
    [profiles, query, sort],
  );
  const selectedRows = useMemo(
    () => profiles.filter((row) => selected.has(row.profile_id)),
    [profiles, selected],
  );
  const selectedProfile = selectedRows.length === 1 ? selectedRows[0] : null;

  const toggle = (id) => setSelected((current) => {
    const next = new Set(current);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });
  const toggleAll = () => setSelected((current) => (
    visibleProfiles.length > 0 && visibleProfiles.every((row) => current.has(row.profile_id))
      ? new Set([...current].filter((id) => !visibleProfiles.some((row) => row.profile_id === id)))
      : new Set([...current, ...visibleProfiles.map((row) => row.profile_id)])
  ));

  const exportAccountData = async (kind) => {
    try {
      // The desktop bridge owns the native save-location dialog and writes
      // only the backend's safe account-metadata export. The product shell
      // does not create client-side downloads.
      if (!selected.size) {
        notify("Select at least one profile before exporting account data.", "error");
        return;
      }
      const result = await call("save_account_export", kind, [...selected]);
      if (result?.cancelled) {
        notify("Account-data export cancelled.");
        return;
      }
      if (!result?.saved) throw new Error("Account-data export was not saved.");
      notify(`${kind.toUpperCase()} account-data export saved${result.filename ? `: ${result.filename}` : "."}`);
    } catch (error) {
      notify(error.message, "error");
    }
  };

  const launch = async () => {
    try {
      const jobId = await call("launch_batch", [...selected], Number(delay));
      setBatch({
        jobId,
        status: "running",
        progress: { completed: 0, total: selected.size },
        onCancel: () => call("cancel_batch", jobId),
      });
    } catch (error) {
      notify(error.message, "error");
    }
  };

  useEffect(() => {
    if (!batch?.jobId) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const state = await call("get_job", batch.jobId);
        setBatch((current) => ({ ...current, ...state, onCancel: current?.onCancel }));
        if (["completed", "failed", "cancelled"].includes(state.status)) {
          window.clearInterval(timer);
          if (state.status === "completed") notify("Batch launch complete.");
          if (state.status === "failed") notify(state.error || "Batch launch failed.", "error");
          if (state.status !== "cancelled" && state.result?.profiles?.length) {
            if (!applyProfileDelta(state.result.profiles)) {
              notify("Launch completed, but the table could not apply the returned profile updates. Use Refresh to resynchronize.", "error");
            }
          }
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 300);
    return () => window.clearInterval(timer);
  }, [applyProfileDelta, batch?.jobId, notify]);

  const deleteSelected = async () => {
    if (deleteInFlight || !selected.size) return;
    // Snapshot stable IDs before the confirmation dialog and before any table
    // refresh can change selection state.
    const profileIds = [...selected];
    if (!window.confirm(`Delete ${profileIds.length} selected profile(s)? Their isolated browser data will be removed.`)) return;
    setDeleteInFlight(true);
    try {
      const result = await call("delete_profiles", profileIds, true);
      const failureText = result.failed ? ` ${result.failed} failed.` : "";
      notify(`${result.deleted} profile(s) deleted.${failureText}`, result.failed ? "error" : "success");
      const deletedIds = Array.isArray(result.deleted_profile_ids)
        ? result.deleted_profile_ids
        : (result.results || []).filter((item) => item.status === "deleted").map((item) => item.profile_id);
      const deltaApplied = applyProfileDelta([], deletedIds);
      if (Number(result.deleted || 0) !== deletedIds.length || !deltaApplied) {
        notify("Deletion succeeded, but the table could not apply the returned profile IDs. Use Refresh to resynchronize.", "error");
      }
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setDeleteInFlight(false);
    }
  };

  return (
    <div className="app-shell bg-ink text-slate-200">
      <Header
        query={query}
        onQuery={setQuery}
        sort={sort}
        onSort={setSort}
        onRefresh={loadProfiles}
        refreshing={refreshing}
      />
      <main className="app-main">
        <div className="dashboard-content">
          <div className="grid flex-none grid-cols-3 gap-3">
            <Summary icon={Activity} label="Total profiles" value={profiles.length} />
            <Summary icon={ShieldCheck} label="Running now" value={profiles.filter((row) => row.status === "Running").length} tone="mint" />
            <Summary icon={Globe2} label="Proxy enabled" value={profiles.filter((row) => row.proxy?.enabled).length} tone="amber" />
          </div>
          <ProfileTable
            rows={visibleProfiles}
            selected={selected}
            onToggle={toggle}
            onToggleAll={toggleAll}
            onSelect={toggle}
            onEdit={(row) => setModal({ type: "edit", profile: row })}
          />
          <div className="panel flex flex-none items-center justify-between gap-3 p-4">
            <div>
              <p className="eyebrow">Selected workspace</p>
              <p className="mt-1 text-sm text-slate-300">{selectedProfile ? `${selectedProfile.stt} · ${selectedProfile.name}` : "Select one profile to see its details"}</p>
            </div>
            {runtime && <p className="text-xs text-slate-500">{runtime.runtime_name} {runtime.browser_version} · {runtime.browser_available ? "Ready" : "Runtime missing"}</p>}
          </div>
        </div>
        <RightSidebar
          selectedCount={selected.size}
          delay={delay}
          onDelay={setDelay}
          onLaunch={launch}
          onCreate={() => setModal({ type: "create" })}
          onImport={() => setModal({ type: "import" })}
          onExport={exportAccountData}
          onEdit={() => selectedProfile && setModal({ type: "edit", profile: selectedProfile })}
          onDelete={deleteSelected}
          deleteInFlight={deleteInFlight}
          onClear={() => setSelected(new Set())}
          onCheckProxy={() => setModal({ type: "check", profile: selectedProfile })}
          batch={batch}
        />
      </main>
      {(modal?.type === "create" || modal?.type === "edit") && (
        <ProfileEditorModal
          profile={modal.profile}
          onClose={() => setModal(null)}
          onSaved={handleProfileSaved}
          notify={notify}
        />
      )}
      {modal?.type === "import" && <BatchImportDialog onClose={() => setModal(null)} onDone={handleImportDone} notify={notify} />}
      {modal?.type === "check" && <ProxyCheckDialog profile={modal.profile} onClose={() => setModal(null)} notify={notify} />}
      <Toasts items={toasts} onDismiss={(id) => setToasts((items) => items.filter((item) => item.id !== id))} />
    </div>
  );
}

function Summary({ icon: Icon, label, value, tone }) {
  return <div className="panel flex items-center gap-3 p-4"><div className={`grid h-9 w-9 place-items-center rounded-lg ${tone === "mint" ? "bg-mint/10 text-mint" : tone === "amber" ? "bg-amber-300/10 text-amber-200" : "bg-accent/10 text-accent"}`}><Icon className="h-4 w-4" /></div><div><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-lg font-semibold text-white">{value}</p></div></div>;
}
