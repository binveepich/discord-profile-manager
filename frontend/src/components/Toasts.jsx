export default function Toasts({ items, onDismiss }) {
  return <div className="fixed bottom-5 right-5 z-50 flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2">{items.map((item) => <button key={item.id} onClick={() => onDismiss(item.id)} className={`rounded-xl border px-4 py-3 text-left text-sm shadow-panel ${item.type === "error" ? "border-rose-400/30 bg-[#28151d] text-rose-200" : "border-mint/30 bg-[#12241f] text-mint"}`}>{item.message}</button>)}</div>;
}
