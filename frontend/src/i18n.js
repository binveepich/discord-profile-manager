export const UI = {
  appName: "Trình quản lý đa tài khoản Discord",
  devStatus: "Phiên bản phát triển · Pre-final",
  nav: {
    profiles: "Hồ sơ",
    settings: "Cài đặt",
    about: "Thông Tin",
  },
  theme: {
    light: "Sáng",
    dark: "Tối",
  },
  status: {
    Running: "Đang mở",
    Closed: "Đã đóng",
    Error: "Có lỗi",
  },
};

const SAFE_ERROR_PATTERNS = [
  [/not found|missing|unavailable/i, "Không tìm thấy thành phần cần thiết. Vui lòng kiểm tra cấu hình rồi thử lại."],
  [/running|close chromium|already open/i, "Hồ sơ đang được sử dụng. Hãy đóng Chromium rồi thử lại."],
  [/invalid|must be|incomplete|empty/i, "Thông tin chưa hợp lệ hoặc còn thiếu. Vui lòng kiểm tra lại."],
  [/proxy/i, "Không thể xử lý Proxy. Vui lòng kiểm tra địa chỉ và cổng."],
];

export function userError(error, fallback = "Không thể hoàn tất thao tác. Vui lòng thử lại.") {
  const raw = String(error?.message || error || "").trim();
  if (!raw) return fallback;
  const match = SAFE_ERROR_PATTERNS.find(([pattern]) => pattern.test(raw));
  return match ? match[1] : fallback;
}

export function formatCount(value, singular = "mục", plural = "mục") {
  const count = Number(value) || 0;
  return `${count} ${count === 1 ? singular : plural}`;
}

export function formatDate(value) {
  if (!value) return "Chưa từng mở";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Không rõ";
  return date.toLocaleString("vi-VN", { dateStyle: "medium", timeStyle: "short" });
}
