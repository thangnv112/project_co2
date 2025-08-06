# CO₂ Monitoring System

Hệ thống giám sát chất lượng không khí theo thời gian thực sử dụng MQTT, Flask, MariaDB và Telegram Bot. Phù hợp để triển khai tại nhà, lớp học, văn phòng hoặc trong hệ thống giám sát môi trường.

## 🚀 Tính năng chính

- Nhận dữ liệu cảm biến (CO₂, nhiệt độ, độ ẩm) thông qua MQTT
- Hiển thị dữ liệu trực quan và biểu đồ thời gian thực trên Web Dashboard
- Tùy chỉnh ngưỡng cảnh báo cho từng chỉ số
- Gửi cảnh báo qua Telegram khi vượt ngưỡng
- Lưu trữ dữ liệu và lịch sử cảnh báo vào cơ sở dữ liệu MariaDB

## 🛠 Công nghệ sử dụng

- Python 3
- Flask + Flask-SocketIO
- Paho MQTT client
- MariaDB (MySQL tương thích)
- Telegram Bot API
- HTML/CSS + Chart.js (Web Dashboard)

## 📦 Cài đặt

### 1. Clone dự án và tạo môi trường ảo:

```bash
git clone https://github.com/thangnv.112/project_co2.git
cd project_co2
python3 -m venv venv
source venv/bin/activate        # Trên Linux/macOS
venv\Scripts\activate           # Trên Windows
```

### 2. Cài đặt thư viện:

```bash
pip install -r requirements.txt
```

### 3. Tạo file cấu hình môi trường:

```bash
cp .env.example .env
```

Cập nhật các biến trong file `.env`:

```env
FLASK_SECRET_KEY=your-secret-key-here
DB_HOST=localhost
DB_PORT=3306
DB_NAME=co2_monitoring
DB_USER=co2_user
DB_PASSWORD=your-db-password
MQTT_BROKER=localhost
MQTT_PORT=1883
MQTT_TOPIC=sensors/data
TELEGRAM_BOT_TOKEN=your-telegram-token
TELEGRAM_CHAT_ID=your-chat-id
```

## ⚙️ Khởi chạy hệ thống

```bash
python3 server2.py 
python3 test_data.py # 2 tiến trình khác nhau
```

Mở trình duyệt và truy cập:

```
http://localhost:5000/
```

## 📊 Giao diện dashboard

- Xem dữ liệu cảm biến mới nhất
- Biểu đồ trực tiếp theo thời gian
- Cài đặt ngưỡng cảnh báo động
- Lịch sử cảnh báo vượt ngưỡng

## 🔐 Lưu ý bảo mật

- Token Telegram, mật khẩu database... đều nằm trong file `.env`
- Không commit `.env` hoặc thư mục `venv` lên Git
- File `.gitignore` đã được cấu hình để loại trừ các mục nhạy cảm

## 📄 License

MIT License
