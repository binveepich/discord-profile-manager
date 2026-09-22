const tones = {
  Running: "border-mint/30 bg-mint/10 text-mint",
  Closed: "border-slate-600 bg-slate-800/60 text-slate-300",
  Error: "border-rose-400/30 bg-rose-400/10 text-rose-300",
};

export default function StatusBadge({ status }) {
  const tone = tones[status] || tones.Error;
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium ${tone}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status || "Error"}
    </span>
  );
}
