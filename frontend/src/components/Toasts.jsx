import { CheckCircle2, X, XCircle } from "lucide-react";

export default function Toasts({ items, onDismiss }) {
  return <div className="toast-stack" aria-live="polite">{items.map((item) => <div className={`toast ${item.type === "error" ? "toast-error" : "toast-success"}`} key={item.id}><span className="toast-icon">{item.type === "error" ? <XCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}</span><p>{item.message}</p><button onClick={() => onDismiss(item.id)} aria-label="Đóng thông báo"><X className="h-4 w-4" /></button></div>)}</div>;
}
