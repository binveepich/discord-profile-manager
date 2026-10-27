# Trình quản lý đa tài khoản Discord (Discord Profile Manager)

Chào bạn! 👋 Đây là hướng dẫn cài đặt lần đầu, viết cho người dùng Windows chưa từng chạy dự án này. Hãy làm theo từng bước theo đúng thứ tự, mỗi bước đều có lệnh cụ thể. Nếu gặp lỗi, xem mục **Gặp lỗi thường gặp** ở cuối trang.

## 📖 Giới thiệu ngắn

Trình quản lý đa tài khoản Discord giúp bạn tạo nhiều **hồ sơ trình duyệt** tách biệt. Mỗi hồ sơ có cookie, phiên đăng nhập và dữ liệu lưu trữ riêng, và được mở trong một cửa sổ Chromium riêng. Dự án hiện chạy từ mã nguồn; chưa có bản đóng gói `.exe`.

Dự án vẫn đang ở giai đoạn beta. Hiện chưa có bộ kiểm thử tự động, nên việc mở giao diện và chạy trình duyệt thật cần bạn tự kiểm tra trên máy của mình.

## 🧩 Yêu cầu trước khi cài

- **Windows**, đã kiểm thử trên Windows 11.
- **Python 3.13** (khuyến nghị). Tải tại [python.org](https://www.python.org/downloads/). Khi cài, hãy tick ô **Add python.exe to PATH**.
- **Node.js 18 trở lên** (nên dùng bản LTS) để build giao diện React. Đã kiểm thử với Node.js 24.
- **Git** để tải mã nguồn bằng lệnh `git clone`. Nếu không dùng Git, bạn có thể tải ZIP từ trang GitHub của dự án.
- **Microsoft Edge WebView2 Runtime**: cửa sổ giao diện của pywebview dùng thành phần này. Windows 10 và 11 thường đã có sẵn. Nếu cửa sổ không mở, hãy cài thêm runtime này từ trang của Microsoft.
- **Trình duyệt Ungoogled Chromium**: không cần tải tay. Nếu chưa có Chromium, lần chạy đầu tiên ứng dụng tự tải khoảng **197 MB**, nên **cần kết nối Internet** lúc đó. Mỗi bản Chromium chiếm khoảng 400–500 MB đĩa. Chi tiết xem mục **🌐 Trình duyệt (tự động tải)** bên dưới.

## 🛠️ Cài đặt lần đầu

Mở **PowerShell** và làm theo các bước sau.

**Bước 1: Tải mã nguồn**

```powershell
git clone https://github.com/binveepich/discord-profile-manager.git
cd discord-profile-manager
```

Nếu bạn không dùng Git, hãy tải ZIP từ trang GitHub của dự án, giải nén, rồi mở PowerShell trong thư mục vừa giải nén.

**Bước 2: Cài các thư viện Python** (chạy từ thư mục dự án)

```powershell
python -m pip install -r requirements.txt
```

Lệnh này cài `psutil` và `pywebview` đúng phiên bản ghi trong `requirements.txt`.

**Bước 3: Build giao diện React**

Chỉ cần làm một lần, và làm lại mỗi khi giao diện thay đổi:

```powershell
cd frontend
npm ci
npm run build
cd ..
```

Sau bước này, thư mục `frontend\dist\` sẽ được tạo ra.

**Bước 4: Chạy ứng dụng lần đầu**

```powershell
python main.py
```

Nếu thư mục `browser\` chưa có Chromium, lần chạy đầu tiên ứng dụng sẽ tự tải **Ungoogled Chromium** vào đó. Bạn không cần tự tìm hay giải nén trình duyệt.

- Lần này cần **kết nối Internet**, gói tải khoảng **197 MB**.
- Có thể mất vài phút, tùy tốc độ mạng. Khi đang tải, ứng dụng hiện thông báo lúc mở, và bạn xem được thanh tiến trình trong **Cài đặt → Trình duyệt**.
- Cửa sổ quản lý vẫn mở ngay, nhưng bạn cần đợi tải xong rồi mới mở được hồ sơ.

Nếu máy bạn không có mạng, hoặc bạn muốn tự quản lý trình duyệt, xem mục **🧰 Nếu cần tự cài trình duyệt** bên dưới.

## ▶️ Chạy ứng dụng

Từ thư mục dự án, chạy lệnh:

```powershell
python main.py
```

Đây là bản React, và là bản mặc định. Cửa sổ **Trình quản lý đa tài khoản Discord** sẽ mở ra.

Nếu bạn cần dùng bản cũ (giao diện Tkinter):

```powershell
python main.py --legacy
```

Bản cũ chỉ chạy được từ mã nguồn đầy đủ. Bản phát hành không đi kèm thư mục `legacy\`. Bản cũ không tự tải trình duyệt, nên cần có sẵn `browser\chrome.exe` (xem mục **🧰 Nếu cần tự cài trình duyệt**).

Nếu `python main.py` dừng lại và hiện thông báo tiếng Anh "The React frontend is not built yet", nghĩa là bạn chưa làm bước 3. Hãy build giao diện theo bước 3, rồi chạy lại. Trong lúc chờ, bạn có thể dùng `python main.py --legacy`.

## 🌐 Trình duyệt (tự động tải)

Ứng dụng tự tải và quản lý **Ungoogled Chromium** trong thư mục `browser\`. Trong trường hợp bình thường, bạn không cần cài hay cập nhật trình duyệt bằng tay.

- **Cài lần đầu:** ứng dụng cài bản đã kiểm thử, **152.0.7977.82**.
- **Kiểm tra bản mới:** nếu bật tự động (mặc định), mỗi lần mở ứng dụng và có mạng, ứng dụng hỏi GitHub xem có bản Chromium mới hơn không. Bạn cũng có thể bấm **Kiểm tra cập nhật** bất cứ lúc nào.
- **Cập nhật:** vào **Cài đặt → Trình duyệt** và bấm **Cập nhật lên ...** khi nút này hiện ra. Ứng dụng chỉ báo khi có bản mới, và chỉ cài khi bạn bấm. Trước khi cập nhật, hãy đóng mọi cửa sổ Chromium đang mở.
- **Quay về:** khi có bản trước, bấm **Quay về ...** để trở lại bản đó.
- **Dung lượng:** mỗi bản khoảng **400–500 MB**. Sau khi cập nhật, ứng dụng giữ **một** bản cũ để quay về, nên tổng cộng có thể khoảng **800–1000 MB**. Bản cũ hơn nữa sẽ bị xóa ở lần cập nhật sau.
- Cập nhật hoặc quay về **không** thay đổi hồ sơ, cấu hình, tiện ích và nhật ký của bạn (`profiles\`, `config\`, `extensions\`, `logs\`).

## 🧰 Nếu cần tự cài trình duyệt (dự phòng)

Bình thường bạn không cần làm việc này. Hãy dùng mục này nếu máy bạn không có Internet, hoặc bạn đã tắt tự động tải.

**1. Tải đúng gói.** Mở [trang Releases của ungoogled-software/ungoogled-chromium-windows](https://github.com/ungoogled-software/ungoogled-chromium-windows/releases), rồi vào bản [152.0.7977.82-1.1](https://github.com/ungoogled-software/ungoogled-chromium-windows/releases/tag/152.0.7977.82-1.1). Tải file **`ungoogled-chromium_152.0.7977.82-1.1_windows_x64.zip`** (Windows x64, dạng `.zip`).

**2. Giải nén vào `browser\`.** Trong thư mục dự án, tạo thư mục `browser` nếu chưa có:

```powershell
mkdir browser
```

Giải nén file zip, rồi đưa toàn bộ file vào `browser\`, sao cho có file `browser\chrome.exe`. Nếu trong zip có một thư mục bọc bên ngoài, hãy đưa các file bên trong thư mục đó ra `browser\`, không để thêm một lớp thư mục.

**3. Tắt tự động tải (nếu bạn muốn).** Mở **Cài đặt → Trình duyệt** và tắt công tắc **Tự động tải và kiểm tra Chromium**. Công tắc này được lưu trong file `config\browser_runtime.json` (`"auto_download": false`). Bạn cũng có thể tắt bằng lệnh:

```powershell
python -m revamped.browser_runtime auto-download off
```

Khi tắt, ứng dụng không tự tải và không tự kiểm tra bản mới khi mở. Bạn vẫn bấm được các nút trong **Cài đặt → Trình duyệt** khi cần.

**Các lệnh khác** (chạy trong thư mục dự án):

- `python -m revamped.browser_runtime status`: xem bản đang cài và bản trước. Không cần mạng.
- `python -m revamped.browser_runtime install`: tải bản đã ghim khi chưa có `browser\chrome.exe`. Cần mạng.
- `python -m revamped.browser_runtime check`: hỏi GitHub xem có bản mới không. Cần mạng.
- `python -m revamped.browser_runtime update`: cập nhật lên bản mới nhất. Cần mạng.
- `python -m revamped.browser_runtime rollback`: quay về bản trước. Không cần mạng.
- `python -m revamped.browser_runtime auto-download on`: bật lại tự động tải và kiểm tra.

## 💾 Dữ liệu của bạn

- Mọi dữ liệu được lưu trên máy này, bên trong thư mục dự án: `profiles\` (hồ sơ trình duyệt), `config\` (danh sách hồ sơ và cấu hình), `data\`, `legacy\data\`, `legacy\log\`, `logs\`, và `tmp\` (dữ liệu tạm khi kiểm thử).
- Các thư mục trên, cùng với `browser\`, `frontend\node_modules\` và `frontend\dist\`, được cấu hình để Git bỏ qua (xem file `.gitignore`).
- **Ứng dụng không có tính năng sao lưu tự động.** Khi ứng dụng và trình duyệt đã đóng, hãy tự sao chép `config\`, `data\`, `legacy\data\` và `profiles\` sang một thư mục nằm ngoài dự án, tốt nhất là trên ổ đĩa khác.
- Không bao giờ commit hoặc chia sẻ các thư mục `profiles\`, `config\` và `data\`, các file danh sách proxy (ví dụ `proxies*.txt`), cũng như các file chứa tài khoản (ví dụ `*accounts*.txt`).

## ⚠️ Lưu ý quan trọng

Công cụ này dành để quản lý **các tài khoản Discord của chính bạn**. Tự động hóa hoặc điều khiển nhiều tài khoản Discord cùng lúc có thể vi phạm Điều khoản dịch vụ của Discord, và có thể khiến các tài khoản bị khóa hoặc bị cấm. Bạn tự chịu trách nhiệm về cách sử dụng.

Mật khẩu và mã TOTP (nếu bạn nhập) được lưu trên máy này, trong file `config.js` của từng hồ sơ, dưới dạng **văn bản thuần, không mã hóa**. Điều này đúng ở cả bản React lẫn bản cũ. Chức năng xuất danh sách tài khoản cũng ghi mật khẩu và mã TOTP vào file xuất. Hãy bảo vệ máy tính bằng mật khẩu đăng nhập Windows, không để người khác dùng chung, và xóa các file xuất khi không còn cần.

## 🔧 Gặp lỗi thường gặp

- **`python` không được nhận dạng.** Cài lại Python, tick **Add python.exe to PATH**, rồi mở lại PowerShell.
- **`node` hoặc `npm` không được nhận dạng.** Cài Node.js 18 trở lên, rồi mở lại PowerShell.
- **"The React frontend is not built yet".** Chạy lại bước 3 (build giao diện).
- **"pywebview is not installed".** Chạy lại `python -m pip install -r requirements.txt` trong thư mục dự án.
- **"Chromium browser runtime not found"** (hoặc "Chưa tìm thấy browser/chrome.exe"). Thường ứng dụng tự tải Chromium khi mở lần đầu. Nếu không tải được, thường vì mất mạng, không vào được GitHub, hoặc hết dung lượng đĩa, hãy kiểm tra mạng và dung lượng, rồi mở **Cài đặt → Trình duyệt** và bấm **Tải Chromium**. Nếu vẫn không được, làm theo mục **🧰 Nếu cần tự cài trình duyệt**.
- **Git báo "dubious ownership"** (thường gặp khi thư mục được sao chép từ một tài khoản Windows khác). Chạy lệnh sau, thay đường dẫn bằng đường dẫn thật của thư mục dự án và dùng dấu `/`:

```powershell
git config --global --add safe.directory "C:/duong/dan/den/discord-profile-manager"
```

- **Cửa sổ không mở.** Kiểm tra Microsoft Edge WebView2 Runtime đã được cài chưa, rồi chạy lại.

## 🧑‍💻 Dành cho nhà phát triển

- Kiểm tra cấu trúc mã nguồn (không mở trình duyệt hay cửa sổ):

```powershell
python -B scripts/verify.py
```

Bộ kiểm thử tự động đã được gỡ khỏi dự án ở bước beta 16, nên các kiểm tra thủ công trong [docs/MANUAL_ACCEPTANCE.md](docs/MANUAL_ACCEPTANCE.md) là bắt buộc.

- Quản lý Chromium bằng dòng lệnh: `python -B -m revamped.browser_runtime status` (chỉ đọc, không cần mạng). Các lệnh `check`, `install` và `update` cần mạng; `rollback` quay về bản trước và không cần mạng.
- Trạng thái dự án và các milestone: [REFACTOR_STATUS.md](REFACTOR_STATUS.md)
- Kiểm tra thủ công trước khi phát hành (tiếng Anh): [docs/MANUAL_ACCEPTANCE.md](docs/MANUAL_ACCEPTANCE.md)
- Thông tin về sản phẩm, sao lưu và snapshot (tiếng Anh): [docs/PRODUCT_CANDIDATE.md](docs/PRODUCT_CANDIDATE.md)

Chúc bạn cài đặt thuận lợi! 🎉
