import { useLayoutEffect, useRef, useState } from "react";
import { Edit3, ExternalLink, MoreHorizontal } from "lucide-react";
import ActionTooltip from "./ActionTooltip";
import StatusBadge from "./StatusBadge";
import { formatDate } from "../i18n";
import { exitMotionDuration } from "../motion";

export default function ProfileTable({ rows, selected, onToggle, onToggleAll, onEdit, onOpen, visibleColumns }) {
  const [exitingRows, setExitingRows] = useState([]);
  const previousRows = useRef(rows);
  const exitTimers = useRef(new Map());
  const rowElements = useRef(new Map());
  const previousPositions = useRef(new Map());
  const animationFrames = useRef(new Set());
  const shownIds = useRef(new Set());
  const staggerIndex = useRef(new Map());
  const [entering, setEntering] = useState(() => new Set());
  const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.profile_id));
  const columns = new Set(visibleColumns || ["account", "environment", "last_opened"]);
  const currentIds = new Set(rows.map((row) => row.profile_id));
  const exitIds = new Set(exitingRows.map((row) => row.profile_id).filter((id) => !currentIds.has(id)));
  const displayedRows = [...rows, ...exitingRows.filter((row) => !currentIds.has(row.profile_id))];

  useLayoutEffect(() => {
    const nextIds = new Set(rows.map((row) => row.profile_id));
    const removed = previousRows.current.filter((row) => !nextIds.has(row.profile_id));
    rows.forEach((row) => {
      const timer = exitTimers.current.get(row.profile_id);
      if (timer) window.clearTimeout(timer);
      exitTimers.current.delete(row.profile_id);
    });
    if (removed.length) {
      setExitingRows((current) => {
        const retained = current.filter((row) => !nextIds.has(row.profile_id));
        return [...retained.filter((row) => !removed.some((item) => item.profile_id === row.profile_id)), ...removed];
      });
      removed.forEach((row) => {
        window.clearTimeout(exitTimers.current.get(row.profile_id));
        const timer = window.setTimeout(() => {
          setExitingRows((current) => current.filter((item) => item.profile_id !== row.profile_id));
          exitTimers.current.delete(row.profile_id);
        }, exitMotionDuration());
        exitTimers.current.set(row.profile_id, timer);
      });
    }
    previousRows.current = rows;
  }, [rows]);

  useLayoutEffect(() => {
    const positions = new Map();
    const reduceMotion = document.documentElement.dataset.reduceMotion === "true";
    const moved = [];
    rows.forEach((row) => {
      const element = rowElements.current.get(row.profile_id);
      if (!element) return;
      const top = element.getBoundingClientRect().top;
      const previousTop = previousPositions.current.get(row.profile_id);
      if (!reduceMotion && previousTop !== undefined && Math.abs(previousTop - top) > 1) moved.push({ element, offset: previousTop - top });
      positions.set(row.profile_id, top);
    });
    if (moved.length) {
      // Write every offset before the one read below, so the browser lays out once instead of once per moved row.
      moved.forEach(({ element, offset }) => {
        element.style.transition = "none";
        element.style.transform = `translateY(${offset}px)`;
      });
      moved[0].element.getBoundingClientRect();
      const frame = window.requestAnimationFrame(() => {
        moved.forEach(({ element }) => {
          element.style.transition = "";
          element.style.transform = "";
        });
        animationFrames.current.delete(frame);
      });
      animationFrames.current.add(frame);
    }
    previousPositions.current = positions;
  }, [rows]);

  useLayoutEffect(() => () => {
    exitTimers.current.forEach((timer) => window.clearTimeout(timer));
    animationFrames.current.forEach((frame) => window.cancelAnimationFrame(frame));
  }, []);

  // Rows in the top eight play the entrance once, when they first appear. The class stays on until that animation ends, because
  // every re-sort moves rows in the DOM, and moving a node restarts any CSS animation still on it.
  const endEntrance = (id) => setEntering((current) => {
    if (!current.has(id)) return current;
    const next = new Set(current);
    next.delete(id);
    return next;
  });
  useLayoutEffect(() => {
    const reduceMotion = document.documentElement.dataset.reduceMotion === "true";
    const starting = [];
    const live = new Set();
    displayedRows.forEach((row, index) => {
      if (exitIds.has(row.profile_id)) return;
      live.add(row.profile_id);
      if (!reduceMotion && index < 8 && !shownIds.current.has(row.profile_id)) {
        starting.push(row.profile_id);
        staggerIndex.current.set(row.profile_id, index);
      }
    });
    shownIds.current = new Set(displayedRows.map((row) => row.profile_id));
    const stale = [...entering].some((id) => !live.has(id));
    if (starting.length || stale) {
      setEntering((current) => {
        const next = new Set([...current].filter((id) => live.has(id)));
        starting.forEach((id) => next.add(id));
        return next;
      });
    }
  });

  return (
    <section className="panel profile-table-panel profile-row-compact flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="table-toolbar">
        <div>
          <h2 className="section-title">Danh sách hồ sơ</h2>
          <p className="section-caption">Chọn một hoặc nhiều hồ sơ để thao tác nhanh</p>
        </div>
        <span className="count-pill">{rows.length} hiển thị</span>
      </div>
      <div className="scrollbar table-scroll min-h-0 flex-1 overflow-y-auto">
        <table className="profile-table text-left text-sm">
          <thead>
            <tr>
              <th className="w-12"><input type="checkbox" checked={allSelected} onChange={onToggleAll} aria-label="Chọn tất cả hồ sơ đang hiển thị" /></th>
              <th className="stt-column">STT</th>
              <th>Tên hồ sơ</th>
              {columns.has("account") && <th>Tài khoản</th>}
              {columns.has("environment") && <th>Môi trường / Proxy</th>}
              <th>Trạng thái</th>
              {columns.has("last_opened") && <th>Mở gần đây</th>}
              <th className="actions-column"><span className="sr-only">Thao tác</span></th>
            </tr>
          </thead>
          <tbody>
            {displayedRows.map((row, index) => {
              const isSelected = selected.has(row.profile_id);
              const isExiting = exitIds.has(row.profile_id);
              const isEntering = !isExiting && entering.has(row.profile_id);
              return (
                <tr
                  key={row.profile_id}
                  ref={(element) => { if (element) rowElements.current.set(row.profile_id, element); else rowElements.current.delete(row.profile_id); }}
                  onClick={() => { if (!isExiting) onToggle(row.profile_id); }}
                  className={`profile-row profile-row-flip ${isSelected ? "profile-row-selected" : ""} ${isExiting ? "profile-row-exit" : isEntering ? "profile-row-enter" : ""}`}
                  style={isEntering ? { "--motion-stagger-index": staggerIndex.current.get(row.profile_id) } : undefined}
                  onAnimationEnd={(event) => { if (event.target === event.currentTarget) endEntrance(row.profile_id); }}
                  aria-hidden={isExiting || undefined}
                >
                  <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={isSelected} onChange={() => onToggle(row.profile_id)} aria-label={`Chọn ${row.name}`} /></td>
                  <td className="stt-column font-mono text-xs">{row.stt}</td>
                  <td>
                    <div className="profile-name">{row.name}</div>
                    <div className="profile-id">{row.profile_id}</div>
                  </td>
                  {columns.has("account") && <td className="account-cell">{row.account || <span className="muted">Chưa có tài khoản</span>}</td>}
                  {columns.has("environment") && <td>
                    <div className="table-primary">{row.environment?.label || "Auto"}</div>
                    <div className={row.proxy?.enabled ? "proxy-on" : "muted table-secondary"}>{row.proxy?.enabled ? `${row.proxy.scheme?.toUpperCase()} · ${row.proxy.host}:${row.proxy.port}` : "Kết nối trực tiếp"}</div>
                  </td>}
                  <td><StatusBadge status={row.status} /></td>
                  {columns.has("last_opened") && <td className="table-secondary">{formatDate(row.last_opened)}</td>}
                  <td onClick={(event) => event.stopPropagation()}>
                    <div className="row-actions">
                      <ActionTooltip label="Mở hồ sơ">
                        <button className="row-action row-open" onClick={() => onOpen(row)} aria-label={`Mở ${row.name}`}><ExternalLink className="h-4 w-4" /></button>
                      </ActionTooltip>
                      <ActionTooltip label="Chỉnh sửa hồ sơ">
                        <button className="row-action" onClick={() => onEdit(row)} aria-label={`Chỉnh sửa ${row.name}`}><Edit3 className="h-4 w-4" /></button>
                      </ActionTooltip>
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
