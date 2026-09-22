import { useState } from "react";
import { FileUp, X } from "lucide-react";
import { call } from "../api/bridge";

export default function BatchImportDialog({ onClose, onDone, notify }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState("");
  const [progress, setProgress] = useState(null);
  const [summary, setSummary] = useState(null);

  const importText = async () => {
    if (!text.trim()) return notify("Paste at least one account line.", "error");
    setBusy(true);
    setSummary(null);
    setProgress(null);
    try {
      // One bridge call starts one Python background job. Individual profile
      // setup and rollback stay backend-authoritative.
      const job = await call("import_accounts_txt", text);
      let state;
      do {
        await new Promise((resolve) => setTimeout(resolve, 250));
        state = await call("get_job", job);
        if (state.progress) setProgress(state.progress);
      } while (["queued", "running"].includes(state.status));
      if (state.status === "failed") throw new Error(state.error);
      const result = state.result || {};
      setSummary(result);
      notify(`Import complete: ${result.created || 0} created, ${result.skipped || 0} skipped, ${result.failed || 0} failed.`);
      onDone(result);
    } catch (error) {
      const message = error.message || "Import failed.";
      setSummary({
        total: progress?.total || 0,
        created: progress?.created || 0,
        skipped: progress?.skipped || 0,
        failed: progress?.failed || 0,
        errors: [{ line: "-", message }],
      });
      notify(message, "error");
    } finally {
      setBusy(false);
    }
  };

  const loadFile = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result || ""));
    reader.readAsText(file);
  };

  return <div className="modal-backdrop"><div className="modal-card max-w-xl"><div className="flex items-center justify-between border-b border-line px-6 py-5"><div><p className="eyebrow">Batch import</p><h2 className="mt-1 text-lg font-semibold text-white">Add accounts from TXT</h2></div><button className="icon-button" onClick={onClose}><X className="h-4 w-4" /></button></div><div className="space-y-4 p-6"><label className="secondary-button w-fit cursor-pointer"><FileUp className="h-4 w-4" />{fileName || "Choose TXT file"}<input type="file" accept=".txt,text/plain" className="hidden" onChange={loadFile} /></label><textarea className="control min-h-[220px] w-full resize-y font-mono text-xs" placeholder={"one@example.com:password:2fa\ntwo@example.com:password"} value={text} onChange={(event) => setText(event.target.value)} /><p className="text-xs leading-5 text-slate-500">Blank lines and lines beginning with # are ignored. Each valid line gets a profile, generated environment, and its own Autofill staging copy. Invalid lines report only their line number and a safe error.</p>{busy && <div className="rounded-lg border border-line bg-elevated p-3 text-xs text-slate-400"><div className="mb-2 flex justify-between"><span>Importing in background</span><span>{progress?.completed || 0}/{progress?.total || 0}</span></div><div className="h-1.5 overflow-hidden rounded-full bg-slate-800"><div className="h-full bg-accent transition-all" style={{ width: `${progress?.total ? ((progress.completed || 0) / progress.total) * 100 : 0}%` }} /></div></div>}{summary && <div className="space-y-2 rounded-lg border border-line bg-elevated p-3 text-xs text-slate-400"><p>Total {summary.total} · Created {summary.created} · Skipped {summary.skipped} · Failed {summary.failed}</p>{summary.errors?.length > 0 && <div className="max-h-28 overflow-y-auto text-rose-300">{summary.errors.map((error) => <div key={`${error.line}-${error.message}`}>Line {error.line}: {error.message}</div>)}</div>}</div>}</div><div className="flex justify-end gap-2 border-t border-line px-6 py-4"><button className="secondary-button" onClick={onClose}>Close</button><button className="primary-button" disabled={busy} onClick={importText}>{busy ? "Importing..." : "Start import"}</button></div></div></div>;
}
