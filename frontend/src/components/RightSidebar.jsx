import { useState } from "react";
import { CheckCircle2, Download, FileText, FolderPlus, Import, Play, Trash2, X } from "lucide-react";

function ActionButton({ icon: Icon, children, onClick, disabled, tone = "default" }) {
  return <button onClick={onClick} disabled={disabled} className={`action-button ${tone === "danger" ? "action-danger" : ""}`}><Icon className="h-4 w-4" />{children}</button>;
}

export default function RightSidebar({ selectedCount, delay, onDelay, onLaunch, onCreate, onImport, onExport, onEdit, onDelete, onClear, onCheckProxy, batch, deleteInFlight, collapsed }) {
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState("");

  const requestExport = async (kind) => {
    setExporting(kind);
    try { await onExport(kind); setExportOpen(false); } finally { setExporting(""); }
  };

  if (collapsed) return null;
  return <aside className="sidebar flex w-full flex-col gap-4 xl:w-[292px]">
    <div className="panel sidebar-card">
      <div className="card-heading"><p className="eyebrow">Mở nhanh</p><h2 className="section-title">Mở các hồ sơ đã chọn</h2></div>
      <div className="card-body space-y-3">
        <label className="field-label">Độ trễ giữa các lần mở <span className="muted">(giây)</span><input type="number" min="0" max="60" step="0.5" value={delay} onChange={(event) => onDelay(event.target.value)} className="control mt-2 w-full" /></label>
        <button className="primary-button w-full justify-center" disabled={!selectedCount || batch?.status === "running" || deleteInFlight} onClick={onLaunch}><Play className="h-4 w-4 fill-current" />{batch?.status === "running" ? "Đang mở…" : `Mở ${selectedCount || "hồ sơ đã chọn"}`}</button>
        {batch && <div className="progress-box"><div className="progress-label"><span>{batch.status === "running" ? "Đang mở hồ sơ" : batch.status === "completed" ? "Đã hoàn tất" : batch.status === "cancelled" ? "Đã hủy" : "Có lỗi"}</span><span>{batch.progress?.completed || 0}/{batch.progress?.total || 0}</span></div><div className="progress-track"><div className="progress-value" style={{ width: `${batch.progress?.total ? ((batch.progress.completed || 0) / batch.progress.total) * 100 : 0}%` }} /></div>{batch.status === "running" && <button className="cancel-button" onClick={batch.onCancel}><X className="h-3.5 w-3.5" />Hủy thao tác</button>}</div>}
      </div>
    </div>

    <div className="panel sidebar-card">
      <div className="card-heading"><p className="eyebrow">Tác vụ quản lý</p></div>
      <div className="card-actions">
        <ActionButton icon={FolderPlus} onClick={onCreate}>Tạo hồ sơ</ActionButton>
        <ActionButton icon={Import} onClick={onImport}>Nhập hồ sơ từ TXT</ActionButton>
        <ActionButton icon={Download} disabled={!selectedCount} onClick={() => setExportOpen((open) => !open)}>Xuất dữ liệu tài khoản</ActionButton>
        {exportOpen && <div className="export-panel"><p className="warning-copy">Tệp xuất có thể chứa dữ liệu nhạy cảm. Chỉ lưu ở nơi an toàn và không chia sẻ công khai.</p><div className="grid grid-cols-3 gap-1"><button className="secondary-button justify-center" disabled={Boolean(exporting)} onClick={() => requestExport("json")}>{exporting === "json" ? "Đang lưu…" : "JSON"}</button><button className="secondary-button justify-center" disabled={Boolean(exporting)} onClick={() => requestExport("csv")}>{exporting === "csv" ? "Đang lưu…" : "CSV"}</button><button className="secondary-button justify-center" disabled={Boolean(exporting)} onClick={() => requestExport("txt")}>{exporting === "txt" ? "Đang lưu…" : "TXT"}</button></div><p className="hint-copy"><FileText className="h-3 w-3" /> Chỉ xuất các hồ sơ đã chọn.</p></div>}
      </div>
    </div>

    <div className="panel sidebar-card">
      <div className="card-heading"><p className="eyebrow">Hồ sơ đã chọn</p><p className="section-caption">{selectedCount ? `${selectedCount} hồ sơ` : "Chưa chọn hồ sơ"}</p></div>
      <div className="card-actions"><ActionButton icon={FolderPlus} disabled={selectedCount !== 1 || deleteInFlight} onClick={onEdit}>Chỉnh sửa hồ sơ</ActionButton><ActionButton icon={CheckCircle2} disabled={selectedCount !== 1 || deleteInFlight} onClick={onCheckProxy}>Kiểm tra Proxy</ActionButton><ActionButton icon={Trash2} tone="danger" disabled={!selectedCount || deleteInFlight} onClick={onDelete}>{deleteInFlight ? "Đang xóa…" : "Xóa hồ sơ đã chọn"}</ActionButton><ActionButton icon={X} disabled={!selectedCount || deleteInFlight} onClick={onClear}>Bỏ chọn</ActionButton></div>
    </div>
  </aside>;
}
