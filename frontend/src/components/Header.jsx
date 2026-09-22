import { ChevronDown, RefreshCw, Search, SlidersHorizontal } from "lucide-react";

export default function Header({ query, onQuery, sort, onSort, onRefresh, refreshing }) {
  return (
    <header className="flex flex-none flex-col gap-5 border-b border-line/80 px-6 py-5 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-accent text-white shadow-lg shadow-accent/20">
          <span className="text-lg font-black">D</span>
        </div>
        <div>
          <h1 className="text-base font-semibold tracking-wide text-white">Discord Profile Manager</h1>
          <p className="mt-0.5 text-xs text-slate-500">Isolated browser workspace</p>
        </div>
      </div>
      <div className="flex flex-1 flex-wrap items-center justify-end gap-2 lg:ml-8">
        <label className="relative min-w-[220px] flex-1 lg:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search profiles, accounts, proxy..." className="control w-full pl-9" />
        </label>
        <div className="relative">
          <SlidersHorizontal className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <select value={sort} onChange={(event) => onSort(event.target.value)} className="control appearance-none pl-9 pr-9">
            <option value="stt">STT order</option>
            <option value="name">Name</option>
            <option value="id">ID</option>
            <option value="status">Status</option>
            <option value="last_opened">Last opened</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-2.5 h-4 w-4 text-slate-500" />
        </div>
        <button className="icon-button" onClick={onRefresh} title="Refresh profile list" disabled={refreshing}><RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} /></button>
      </div>
    </header>
  );
}
