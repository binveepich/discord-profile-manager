import { Edit3, MoreHorizontal } from "lucide-react";
import StatusBadge from "./StatusBadge";

export default function ProfileTable({ rows, selected, onToggle, onToggleAll, onEdit, onSelect }) {
  const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.profile_id));
  return (
    <section className="panel profile-table-panel flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-line/80 px-5 py-4">
        <div><h2 className="text-sm font-semibold text-white">Profiles</h2><p className="mt-1 text-xs text-slate-500">Select one or more isolated workspaces</p></div>
        <span className="rounded-full bg-elevated px-3 py-1 text-xs text-slate-400">{rows.length} visible</span>
      </div>
      <div className="scrollbar table-scroll min-h-0 flex-1 overflow-x-auto overflow-y-auto">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead className="sticky top-0 z-10 bg-panel/95 text-[11px] uppercase tracking-[.12em] text-slate-500 backdrop-blur">
            <tr>
              <th className="w-12 px-5 py-3"><input type="checkbox" checked={allSelected} onChange={onToggleAll} aria-label="Select all visible profiles" /></th>
              <th className="px-3 py-3">STT</th><th className="px-3 py-3">Name</th><th className="px-3 py-3">Account</th><th className="px-3 py-3">Environment / Proxy</th><th className="px-3 py-3">Status</th><th className="px-3 py-3">Last opened</th><th className="w-16 px-3 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line/60">
            {rows.map((row) => {
              const isSelected = selected.has(row.profile_id);
              return <tr key={row.profile_id} onClick={() => onSelect(row.profile_id)} className={`group cursor-pointer transition-colors ${isSelected ? "bg-accent/10" : "hover:bg-elevated/70"}`}>
                <td className="px-5 py-4" onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={isSelected} onChange={() => onToggle(row.profile_id)} aria-label={`Select ${row.name}`} /></td>
                <td className="px-3 py-4 font-mono text-xs text-slate-500">{row.stt}</td>
                <td className="px-3 py-4"><div className="font-medium text-slate-100">{row.name}</div><div className="mt-1 font-mono text-[10px] text-slate-600">{row.profile_id}</div></td>
                <td className="max-w-[210px] truncate px-3 py-4 text-slate-300">{row.account || <span className="text-slate-600">No account</span>}</td>
                <td className="px-3 py-4"><div className="text-slate-300">{row.environment?.label || "Desktop"}</div><div className={`mt-1 text-xs ${row.proxy?.enabled ? "text-amber-300" : "text-slate-600"}`}>{row.proxy?.enabled ? `${row.proxy.scheme?.toUpperCase()} · ${row.proxy.host}:${row.proxy.port}` : "Direct connection"}</div></td>
                <td className="px-3 py-4"><StatusBadge status={row.status} /></td>
                <td className="px-3 py-4 text-xs text-slate-400">{row.last_opened ? new Date(row.last_opened).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "Never"}</td>
                <td className="px-3 py-4" onClick={(event) => event.stopPropagation()}><button className="row-action" onClick={() => onEdit(row)} title="Edit profile"><Edit3 className="h-4 w-4" /></button></td>
              </tr>;
            })}
          </tbody>
        </table>
        {!rows.length && <div className="grid h-48 place-items-center text-sm text-slate-500">No profiles match this view.</div>}
      </div>
      <div className="flex flex-none items-center justify-between border-t border-line/80 px-5 py-3 text-xs text-slate-500"><span><MoreHorizontal className="mr-2 inline h-4 w-4" />Profile order is stable; sorting changes the view only.</span><span>Maximum 9,999</span></div>
    </section>
  );
}
