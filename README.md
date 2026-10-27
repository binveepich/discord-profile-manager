# Trình quản lý đa tài khoản Discord (Discord Profile Manager)

Chào bạn! 👋 Đây là hướng dẫn cài đặt lần đầu, viết cho người dùng Windows chưa từng chạy dự án này. Hãy làm theo từng bước theo đúng thứ tự, mỗi bước đều có lệnh cụ thể. Nếu gặp lỗi, xem mục **Gặp lỗi thường gặp** ở cuối trang.

## 📖 Giới thiệu ngắn

Trình quản lý đa tài khoản Discord giúp bạn tạo nhiều **hồ sơ trình duyệt** tách biệt. Mỗi hồ sơ có cookie, phiên đăng nhập và dữ liệu lưu trữ riêng, và được mở trong một cửa sổ Chromium riêng. Dự án hiện chạy từ mã nguồn; chưa có bản đóng gói `.exe`.

Dự án vẫn đang ở giai đoạn beta. Các kiểm tra tự động đã đạt, nhưng việc mở giao diện và chạy trình duyệt thật cần bạn tự kiểm tra trên máy của mình.

## 🧩 Yêu cầu trước khi cài

- **Windows**, đã kiểm thử trên Windows 11.
- **Python 3.13** (khuyến nghị). Tải tại [python.org](https://www.python.org/downloads/). Khi cài, hãy tick ô **Add python.exe to PATH**.
- **Node.js 18 trở lên** (nên dùng bản LTS) để build giao diện React. Đã kiểm thử với Node.js 24.
- **Git** để tải mã nguồn bằng lệnh `git clone`. Nếu không dùng Git, bạn có thể tải ZIP từ trang GitHub của dự án.
- **Microsoft Edge WebView2 Runtime**: cửa sổ giao diện của pywebview dùng thành phần này. Windows 10 và 11 thường đã có sẵn. Nếu cửa sổ không mở, hãy cài thêm runtime này từ trang của Microsoft.
- **Trình duyệt Ungoogled Chromium** (bản Windows, đủ toàn bộ các file của runtime). Bạn đặt vào thư mục `browser\`. Ứng dụng không tự cài hay cập nhật trình duyệt.

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

**Bước 4: Đặt trình duyệt**

Tạo thư mục `browser` trong thư mục dự án (nếu chưa có), rồi đặt toàn bộ file của Ungoogled Chromium vào đó, sao cho có file `browser\chrome.exe`:

```powershell
mkdir browser
```

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

Bản cũ chỉ chạy được từ mã nguồn đầy đủ. Bản phát hành không đi kèm thư mục `legacy\`.

Nếu `python main.py` dừng lại và hiện thông báo tiếng Anh "The React frontend is not built yet", nghĩa là bạn chưa làm bước 3. Hãy build giao diện theo bước 3, rồi chạy lại. Trong lúc chờ, bạn có thể dùng `python main.py --legacy`.

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
- **"Chromium browser runtime not found".** Kiểm tra file `browser\chrome.exe` có nằm đúng đường dẫn mà thông báo đã in ra không.
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

- Trạng thái dự án và các milestone: [REFACTOR_STATUS.md](REFACTOR_STATUS.md)
- Kiểm tra thủ công trước khi phát hành (tiếng Anh): [docs/MANUAL_ACCEPTANCE.md](docs/MANUAL_ACCEPTANCE.md)
- Thông tin về sản phẩm, sao lưu và snapshot (tiếng Anh): [docs/PRODUCT_CANDIDATE.md](docs/PRODUCT_CANDIDATE.md)

Chúc bạn cài đặt thuận lợi! 🎉
