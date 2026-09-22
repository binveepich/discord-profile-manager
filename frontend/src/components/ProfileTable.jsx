import { Edit3, ExternalLink, MoreHorizontal } from "lucide-react";
import StatusBadge from "./StatusBadge";
import { formatDate } from "../i18n";

export default function ProfileTable({ rows, selected, onToggle, onToggleAll, onEdit, onOpen, visibleColumns, compact }) {
  const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.profile_id));
  const columns = new Set(visibleColumns || ["account", "environment", "status", "last_opened"]);
  const density = compact ? "profile-row-compact" : "";
  return (
    <section className={`panel profile-table-panel flex min-h-0 flex-1 flex-col overflow-hidden ${density}`}>
      <div className="table-toolbar">
        <div>
          <h2 className="section-title">Danh sách hồ sơ</h2>
          <p className="section-caption">Chọn một hoặc nhiều hồ sơ để thao tác nhanh</p>
        </div>
        <span className="count-pill">{rows.length} hiển thị</span>
      </div>
      <div className="scrollbar table-scroll min-h-0 flex-1 overflow-x-auto overflow-y-auto">
        <table className="profile-table w-full min-w-[760px] text-left text-sm">
          <thead>
            <tr>
              <th className="w-12"><input type="checkbox" checked={allSelected} onChange={onToggleAll} aria-label="Chọn tất cả hồ sơ đang hiển thị" /></th>
              <th className="stt-column">STT</th>
              <th>Tên hồ sơ</th>
              {columns.has("account") && <th>Tài khoản</th>}
              {columns.has("environment") && <th>Môi trường / Proxy</th>}
              {columns.has("status") && <th>Trạng thái</th>}
              {columns.has("last_opened") && <th>Mở gần đây</th>}
              <th className="actions-column"><span className="sr-only">Thao tác</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isSelected = selected.has(row.profile_id);
              return (
                <tr key={row.profile_id} onClick={() => onToggle(row.profile_id)} className={isSelected ? "profile-row profile-row-selected" : "profile-row"}>
                  <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={isSelected} onChange={() => onToggle(row.profile_id)} aria-label={`Chọn ${row.name}`} /></td>
                  <td className="stt-column font-mono text-xs">{row.stt}</td>
                  <td>
                    <div className="profile-name">{row.name}</div>
                    <div className="profile-id">{row.profile_id}</div>
                  </td>
                  {columns.has("account") && <td className="account-cell">{row.account || <span className="muted">Chưa có tài khoản</span>}</td>}
                  {columns.has("environment") && <td>
                    <div className="table-primary">{row.environment?.label || "Desktop"}</div>
                    <div className={row.proxy?.enabled ? "proxy-on" : "muted table-secondary"}>{row.proxy?.enabled ? `${row.proxy.scheme?.toUpperCase()} · ${row.proxy.host}:${row.proxy.port}` : "Kết nối trực tiếp"}</div>
                  </td>}
                  {columns.has("status") && <td><StatusBadge status={row.status} /></td>}
                  {columns.has("last_opened") && <td className="table-secondary">{formatDate(row.last_opened)}</td>}
                  <td onClick={(event) => event.stopPropagation()}>
                    <div className="row-actions">
                      <button className="row-action row-open" onClick={() => onOpen(row)} title="Mở hồ sơ" aria-label={`Mở ${row.name}`}><ExternalLink className="h-4 w-4" /></button>
                      <button className="row-action" onClick={() => onEdit(row)} title="Chỉnh sửa hồ sơ" aria-label={`Chỉnh sửa ${row.name}`}><Edit3 className="h-4 w-4" /></button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <div className="empty-state"><div className="empty-state-icon"><MoreHorizontal className="h-5 w-5" /></div><p>Không có hồ sơ phù hợp</p><span>Thử thay đổi từ khóa tìm kiếm hoặc tạo hồ sơ mới.</span></div>}
      </div>
      <div className="table-footer"><span><MoreHorizontal className="mr-2 inline h-4 w-4" />STT và mã hồ sơ được giữ ổn định; sắp xếp chỉ thay đổi cách hiển thị.</span><span>Tối đa 9.999 hồ sơ</span></div>
    </section>
  );
}
