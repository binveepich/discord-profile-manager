import { useEffect, useState } from "react";
import { CheckCircle2, LoaderCircle, X, XCircle } from "lucide-react";
import { call } from "../api/bridge";

export default function ProxyCheckDialog({ profile, onClose, notify }) {
  const [state, setState] = useState({ status: "starting" });
  useEffect(() => {
    let timer;
    let active = true;
    (async () => {
      try {
        if (!profile?.proxy?.enabled) throw new Error("This profile uses a direct connection.");
        const raw = `${profile.proxy.scheme}://${profile.proxy.host}:${profile.proxy.port}`;
        const jobId = await call("check_proxy", raw, 8);
        timer = window.setInterval(async () => {
          try {
            const next = await call("get_job", jobId);
            if (active) setState(next);
            if (["completed", "failed", "cancelled"].includes(next.status)) window.clearInterval(timer);
          } catch (error) { if (active) setState({ status: "failed", error: error.message }); window.clearInterval(timer); }
        }, 300);
      } catch (error) { if (active) setState({ status: "failed", error: error.message }); }
    })();
    return () => { active = false; if (timer) window.clearInterval(timer); };
  }, [profile]);
  const result = state.result;
  return <div className="modal-backdrop"><div className="modal-card max-w-md"><div className="flex items-center justify-between border-b border-line px-6 py-5"><div><p className="eyebrow">Proxy diagnostics</p><h2 className="mt-1 text-lg font-semibold text-white">{profile?.name}</h2></div><button className="icon-button" onClick={onClose}><X className="h-4 w-4" /></button></div><div className="space-y-4 p-6">{state.status === "running" || state.status === "starting" ? <div className="flex items-center gap-3 rounded-lg border border-line bg-elevated p-4 text-sm text-slate-300"><LoaderCircle className="h-5 w-5 animate-spin text-accent" />Checking outbound connection...</div> : result?.alive ? <div className="rounded-lg border border-mint/30 bg-mint/5 p-4"><div className="flex items-center gap-2 text-mint"><CheckCircle2 className="h-5 w-5" /><span className="font-semibold">Alive</span></div><div className="mt-4 grid grid-cols-2 gap-3 text-sm"><Metric label="Outbound IP" value={result.outbound_ip} /><Metric label="Latency" value={`${result.latency_ms} ms`} /><Metric label="Country" value={result.country || "Unavailable"} /><Metric label="City" value={result.city || "Unavailable"} /><Metric label="Provider / ASN" value={[result.provider, result.asn].filter(Boolean).join(" · ") || "Unavailable"} /></div>{result.geography_warning && <p className="mt-3 text-xs text-amber-200">{result.geography_warning}</p>}</div> : <div className="rounded-lg border border-rose-400/30 bg-rose-400/5 p-4"><div className="flex items-center gap-2 text-rose-300"><XCircle className="h-5 w-5" /><span className="font-semibold">Dead</span></div><p className="mt-3 text-sm leading-6 text-rose-200/80">{result?.error || state.error || "The proxy did not respond."}</p></div>}<p className="text-xs leading-5 text-slate-500">Diagnostics run asynchronously. Location data is best-effort and may be unavailable.</p></div><div className="flex justify-end border-t border-line px-6 py-4"><button className="secondary-button" onClick={onClose}>Close</button></div></div></div>;
}

function Metric({ label, value }) { return <div><p className="text-xs text-slate-500">{label}</p><p className="mt-1 truncate text-slate-200">{value}</p></div>; }
