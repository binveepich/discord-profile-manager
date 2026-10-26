import { useEffect, useRef, useState } from "react";
import {
  ArrowDownUp,
  Check,
  Info,
  Moon,
  RefreshCw,
  Search,
  Settings,
  Sun,
} from "lucide-react";
import { UI } from "../i18n";
import { durations } from "../motion";
import usePresence from "../usePresence";

const SORT_OPTIONS = [
  ["stt", "Theo STT"],
  ["name", "Tên hồ sơ"],
  ["id", "Mã hồ sơ"],
  ["status", "Trạng thái"],
  ["last_opened", "Mở gần đây"],
];

export default function Header({
  query,
  onQuery,
  sort,
  onSort,
  onRefresh,
  refreshing,
  theme,
  onThemeChange,
  onSettings,
  onAbout,
}) {
  const [sortOpen, setSortOpen] = useState(false);
  const sortMenu = usePresence(sortOpen);
  const [themePulse, setThemePulse] = useState(null);
  const sortRoot = useRef(null);
  const sortTrigger = useRef(null);
  const optionRefs = useRef([]);
  const themePulseTimer = useRef(null);
  const themePulseFrame = useRef(null);
  const currentSort = SORT_OPTIONS.find(([value]) => value === sort)?.[1] || SORT_OPTIONS[0][1];

  const changeTheme = (nextTheme) => {
    onThemeChange(nextTheme);
    window.clearTimeout(themePulseTimer.current);
    if (themePulseFrame.current !== null) window.cancelAnimationFrame(themePulseFrame.current);
    setThemePulse(null);
    themePulseFrame.current = window.requestAnimationFrame(() => {
      setThemePulse(nextTheme);
      themePulseTimer.current = window.setTimeout(() => setThemePulse(null), durations.fast);
    });
  };

  useEffect(() => () => {
    window.clearTimeout(themePulseTimer.current);
    if (themePulseFrame.current !== null) window.cancelAnimationFrame(themePulseFrame.current);
  }, []);

  useEffect(() => {
    if (!sortOpen) return undefined;
    const onPointerDown = (event) => {
      if (!sortRoot.current?.contains(event.target)) setSortOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setSortOpen(false);
        sortTrigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [sortOpen]);

  const moveSortFocus = (event, index) => {
    let next = null;
    if (event.key === "ArrowDown") next = (index + 1) % SORT_OPTIONS.length;
    else if (event.key === "ArrowUp") next = (index - 1 + SORT_OPTIONS.length) % SORT_OPTIONS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = SORT_OPTIONS.length - 1;
    if (next !== null) {
      event.preventDefault();
      optionRefs.current[next]?.focus();
    }
  };

  const chooseSort = (value) => {
    onSort(value);
    setSortOpen(false);
    sortTrigger.current?.focus();
  };

  return (
    <header className="app-header">
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true"><DiscordIcon /></div>
        <div className="brand-copy">
          <h1 className="brand-title">{UI.appName}</h1>
        </div>
      </div>

      <label className="search-field header-search">
        <Search className="pointer-events-none h-4 w-4" aria-hidden="true" />
        <input
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Tìm hồ sơ, tài khoản, Proxy..."
          aria-label="Tìm kiếm hồ sơ"
        />
      </label>

      <div className="header-tools">
        <div className="sort-control-wrap" ref={sortRoot}>
          <button
            ref={sortTrigger}
            className="sort-trigger"
            type="button"
            onClick={() => setSortOpen((open) => !open)}
            aria-label={`Sắp xếp hồ sơ: ${currentSort}`}
            aria-haspopup="listbox"
            aria-expanded={sortOpen}
            data-tooltip="Sắp xếp hồ sơ"
            title="Sắp xếp hồ sơ"
          >
            <ArrowDownUp className="h-4 w-4" aria-hidden="true" />
            <span>{currentSort}</span>
          </button>
          {sortMenu.mounted && (
            <div className={`sort-menu ${sortMenu.closing ? "popup-exit" : ""}`} role="listbox" aria-label="Sắp xếp hồ sơ">
              {SORT_OPTIONS.map(([value, label], index) => (
                <button
                  key={value}
                  ref={(element) => { optionRefs.current[index] = element; }}
                  className={`sort-option ${sort === value ? "sort-option-active" : ""}`}
                  type="button"
                  role="option"
                  aria-selected={sort === value}
                  onClick={() => chooseSort(value)}
                  onKeyDown={(event) => moveSortFocus(event, index)}
                >
                  <Check className="sort-option-check h-4 w-4" aria-hidden="true" />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          className={`icon-button tooltip-trigger ${refreshing ? "icon-button-busy" : ""}`}
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          aria-label="Làm mới danh sách"
          data-tooltip="Làm mới"
          title="Làm mới"
        >
          <RefreshCw className={refreshing ? "spin-once h-4 w-4" : "h-4 w-4"} />
        </button>
        <div className="theme-switch" role="group" aria-label="Chọn giao diện">
          <button
            className={`theme-option tooltip-trigger ${themePulse === "light" ? "theme-pop" : ""}`}
            type="button"
            onClick={() => changeTheme("light")}
            aria-label="Giao diện sáng"
            aria-pressed={theme === "light"}
            data-tooltip="Giao diện sáng"
            title="Giao diện sáng"
          >
            <Sun className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            className={`theme-option tooltip-trigger ${themePulse === "dark" ? "theme-pop" : ""}`}
            type="button"
            onClick={() => changeTheme("dark")}
            aria-label="Giao diện tối"
            aria-pressed={theme === "dark"}
            data-tooltip="Giao diện tối"
            title="Giao diện tối"
          >
            <Moon className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <button
          className="icon-button tooltip-trigger"
          type="button"
          onClick={onSettings}
          aria-label="Cài đặt"
          data-tooltip="Cài đặt"
          title="Cài đặt"
        >
          <Settings className="h-4 w-4" />
        </button>
        <button
          className="info-button tooltip-trigger"
          type="button"
          onClick={onAbout}
          aria-label="Thông Tin"
          data-tooltip="Thông Tin"
          title="Thông Tin"
        >
          <Info className="h-4 w-4" aria-hidden="true" />
          <span>Thông Tin</span>
        </button>
      </div>
    </header>
  );
}

export function DiscordIcon() {
  return (
    <svg viewBox="0 0 24 24" role="img" aria-label="Discord" focusable="false">
      <path fill="currentColor" d="M19.54 5.36A16.5 16.5 0 0 0 15.42 4l-.5 1.03a15.2 15.2 0 0 0-5.84 0L8.58 4a16.56 16.56 0 0 0-4.12 1.37C1.85 9.23 1.14 13 1.5 16.72a16.6 16.6 0 0 0 5.06 2.58l1.22-1.67c-.67-.25-1.3-.57-1.9-.95l.46-.36c3.67 1.7 8.2 1.7 11.83 0l.46.36c-.59.38-1.23.7-1.9.95l1.22 1.67a16.6 16.6 0 0 0 5.06-2.58c.42-4.32-.72-8.06-3.47-11.36ZM8.56 14.58c-1.1 0-2.01-1.02-2.01-2.27s.89-2.28 2.01-2.28 2.02 1.02 2.02 2.28-.9 2.27-2.02 2.27Zm6.88 0c-1.1 0-2.01-1.02-2.01-2.27s.89-2.28 2.01-2.28 2.02 1.02 2.02 2.28-.9 2.27-2.02 2.27Z" />
    </svg>
  );
}
