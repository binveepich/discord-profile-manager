import {
  CircleHelp,
  Moon,
  RefreshCw,
  Search,
  Settings,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { UI } from "../i18n";

export default function Header({
  query,
  onQuery,
  sort,
  onSort,
  onRefresh,
  refreshing,
  activeView,
  onNavigate,
  theme,
  onThemeCycle,
}) {
  const ThemeIcon = theme === "light" ? Sun : theme === "dark" ? Moon : CircleHelp;
  return (
    <header className="app-header">
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true">D</div>
        <div>
          <h1 className="brand-title">{UI.appName}</h1>
          <p className="brand-subtitle">Quản lý các phiên trình duyệt độc lập</p>
        </div>
      </div>

      <nav className="main-nav" aria-label="Điều hướng chính">
        <button className={`nav-item ${activeView === "profiles" ? "nav-item-active" : ""}`} onClick={() => onNavigate("profiles")}>
          Hồ sơ
        </button>
        <button className={`nav-item ${activeView === "settings" ? "nav-item-active" : ""}`} onClick={() => onNavigate("settings")}>
          <Settings className="h-4 w-4" /> Cài đặt
        </button>
        <button className={`nav-item ${activeView === "about" ? "nav-item-active" : ""}`} onClick={() => onNavigate("about")}>
          <CircleHelp className="h-4 w-4" /> Giới thiệu
        </button>
      </nav>

      <div className="header-tools">
        {activeView === "profiles" && <>
          <label className="search-field">
            <Search className="pointer-events-none h-4 w-4" />
            <input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Tìm hồ sơ, tài khoản, Proxy…" aria-label="Tìm kiếm hồ sơ" />
          </label>
          <label className="sort-field">
            <SlidersHorizontal className="pointer-events-none h-4 w-4" />
            <select value={sort} onChange={(event) => onSort(event.target.value)} aria-label="Sắp xếp hồ sơ">
              <option value="stt">Theo STT</option>
              <option value="name">Tên hồ sơ</option>
              <option value="id">Mã hồ sơ</option>
              <option value="status">Trạng thái</option>
              <option value="last_opened">Mở gần đây</option>
            </select>
          </label>
          <button className="icon-button" onClick={onRefresh} title="Làm mới danh sách" aria-label="Làm mới danh sách" disabled={refreshing}>
            <RefreshCw className={refreshing ? "spin-once h-4 w-4" : "h-4 w-4"} />
          </button>
        </>}
        <button className="theme-button" onClick={onThemeCycle} title="Đổi giao diện" aria-label={`Giao diện: ${UI.theme[theme] || UI.theme.system}`}>
          <ThemeIcon className="h-4 w-4" />
          <span>{UI.theme[theme] || UI.theme.system}</span>
        </button>
      </div>
    </header>
  );
}
