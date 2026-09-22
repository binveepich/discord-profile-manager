import { useState } from "react";
import { CheckCircle2, Download, FileText, FolderPlus, Import, Play, Trash2, X } from "lucide-react";

function ActionButton({ icon: Icon, children, onClick, disabled, tone = "default" }) {
  return <button onClick={onClick} disabled={disabled} className={`action-button profile-area-button ${tone === "danger" ? "text-rose-300 hover:bg-rose-400/10" : "text-slate-300 hover:bg-white/5"}`}><Icon className="h-4 w-4" />{children}</button>;
}

export default function RightSidebar({ selectedCount, delay, onDelay, onLaunch, onCreate, onImport, onExport, onEdit, onDelete, onClear, onCheckProxy, batch, deleteInFlight }) {
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState("");

  const requestExport = async (kind) => {
    setExporting(kind);
    try {
      await onExport(kind);
      setExportOpen(false);
    } finally {
      setExporting("");
    }
  };

  return <aside className="sidebar flex w-full flex-col gap-4 xl:w-[292px]">
    <div className="panel overflow-hidden"><div className="border-b border-line/80 px-5 py-4"><p className="eyebrow">Quick launch</p><h2 className="mt-1 text-sm font-semibold text-white">Open selected profiles</h2></div>
      <div className="space-y-3 p-5"><label className="block text-xs text-slate-500">Launch delay <span className="text-slate-600">(seconds)</span><input type="number" min="0" max="60" step="0.5" value={delay} onChange={(event) => onDelay(event.target.value)} className="control mt-2 w-full" /></label><button className="primary-button profile-area-button w-full justify-center" disabled={!selectedCount || batch?.status === "running" || deleteInFlight} onClick={onLaunch}><Play className="h-4 w-4 fill-current" />{batch?.status === "running" ? "Launching..." : `Launch ${selectedCount || "selected"}`}</button>{batch && <div className="rounded-lg border border-line bg-elevated p-3 text-xs text-slate-400"><div className="mb-2 flex justify-between"><span>{batch.status === "running" ? "Opening profiles" : batch.status}</span><span>{batch.progress?.completed || 0}/{batch.progress?.total || 0}</span></div><div className="h-1.5 overflow-hidden rounded-full bg-slate-800"><div className="h-full bg-accent transition-all" style={{ width: `${batch.progress?.total ? ((batch.progress.completed || 0) / batch.progress.total) * 100 : 0}%` }} /></div>{batch.status === "running" && <button className="mt-3 flex items-center gap-1 text-rose-300" onClick={batch.onCancel}><X className="h-3.5 w-3.5" />Cancel batch</button>}</div>}</div>
    </div>
     <div className="panel"><div className="border-b border-line/80 px-5 py-4"><p className="eyebrow">Manager actions</p></div><div className="p-2"><ActionButton icon={FolderPlus} onClick={onCreate}>Create profile</ActionButton><ActionButton icon={Import} onClick={onImport}>Import accounts TXT</ActionButton><ActionButton icon={Download} disabled={!selectedCount} onClick={() => setExportOpen((open) => !open)}>Export Account Data</ActionButton>{exportOpen && <div className="ml-7 space-y-2 border-l border-line pb-2 pl-3 pr-2"><p className="text-xs leading-5 text-amber-200/80">Choose a filename and folder in the native save dialog. This file contains sensitive credentials: passwords, TOTP secrets, tokens if stored, and proxy username/password. Store it securely.</p><div className="grid grid-cols-3 gap-1"><button className="secondary-button justify-center px-2 py-1.5 text-[11px]" disabled={Boolean(exporting)} onClick={() => requestExport("json")}>{exporting === "json" ? "Saving..." : "JSON"}</button><button className="secondary-button justify-center px-2 py-1.5 text-[11px]" disabled={Boolean(exporting)} onClick={() => requestExport("csv")}>{exporting === "csv" ? "Saving..." : "CSV"}</button><button className="secondary-button justify-center px-2 py-1.5 text-[11px]" disabled={Boolean(exporting)} onClick={() => requestExport("txt")}>{exporting === "txt" ? "Saving..." : "TXT"}</button></div><p className="flex items-center gap-1 text-[10px] text-slate-600"><FileText className="h-3 w-3" />Selected profiles only; JSON, CSV, and pipe-separated TXT use the same field order.</p></div>}</div></div>
    <div className="panel"><div className="border-b border-line/80 px-5 py-4"><p className="eyebrow">Profile actions</p><p className="mt-1 text-xs text-slate-500">{selectedCount ? `${selectedCount} selected` : "Choose a profile"}</p></div><div className="p-2"><ActionButton icon={FolderPlus} disabled={selectedCount !== 1 || deleteInFlight} onClick={onEdit}>Edit profile</ActionButton><ActionButton icon={CheckCircle2} disabled={selectedCount !== 1 || deleteInFlight} onClick={onCheckProxy}>Check proxy</ActionButton><ActionButton icon={Trash2} tone="danger" disabled={!selectedCount || deleteInFlight} onClick={onDelete}>{deleteInFlight ? "Deleting..." : "Delete selected"}</ActionButton><ActionButton icon={X} disabled={!selectedCount || deleteInFlight} onClick={onClear}>Clear selection</ActionButton></div></div>
  </aside>;
}
