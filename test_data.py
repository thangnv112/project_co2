#!/usr/bin/env python3
"""
Script test gửi dữ liệu giả để test hệ thống
Chạy song song với server1.py để xem dashboard hoạt động
"""

import paho.mqtt.client as mqtt
import json
import time
import random
from datetime import datetime

# Cấu hình MQTT
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "sensors/data"


def generate_fake_data():
    """Generate fake sensor data"""
    # Tính AQI dựa trên các thông số khác
    tvoc = random.uniform(100, 1000)  # ppb
    eco2 = random.uniform(300, 1500)  # ppm

    # Tính AQI dựa trên TVOC và eCO2
    if tvoc < 300 and eco2 < 600:
        aqi = 1  # Excellent
    elif tvoc < 500 and eco2 < 800:
        aqi = 2  # Good
    elif tvoc < 700 and eco2 < 1000:
        aqi = 3  # Average
    elif tvoc < 900 and eco2 < 1200:
        aqi = 4  # Poor
    else:
        aqi = 5  # Very Poor

    return {
        "tvoc": tvoc,
        "temperature": round(random.uniform(15, 40), 1),  # °C
        "humidity": round(random.uniform(20, 80), 1),  # %
        "eco2": round(eco2),  # ppm
        "aqi": aqi,  # 1-5 scale
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Kết nối MQTT thành công")
    else:
        print(f"❌ Lỗi kết nối MQTT: {rc}")


def main():
    print("🧪 Bắt đầu test gửi dữ liệu giả...")
    print("📡 MQTT Broker:", MQTT_BROKER)
    print("📊 Topic:", MQTT_TOPIC)
    print("⏱️  Gửi dữ liệu mỗi 5 giây")
    print("🛑 Nhấn Ctrl+C để dừng")
    print("-" * 50)

    # Khởi tạo MQTT client
    client = mqtt.Client()
    client.on_connect = on_connect

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()

        counter = 1
        while True:
            # Tạo dữ liệu giả
            data = generate_fake_data()

            # Chuyển thành JSON
            json_data = json.dumps(data)
            print(f"JSON gửi đi: {json_data}")  # Debug

            # Gửi qua MQTT
            result = client.publish(MQTT_TOPIC, json_data)

            if result.rc == 0:
                print(
                    f"📤 [{counter:03d}] Sent: TVOC={data['tvoc']}mg/m³, T={data['temperature']}°C, H={data['humidity']}%"
                )

                # Hiển thị cảnh báo nếu có
                alerts = []
                if data["tvoc"] > 0.5:
                    alerts.append(f"🚨 TVOC cao ({data['tvoc']}mg/m³)")
                if data["temperature"] > 30:
                    alerts.append(f"🔥 Nhiệt độ cao ({data['temperature']}°C)")
                if data["humidity"] > 70:
                    alerts.append(f"💧 Độ ẩm cao ({data['humidity']}%)")

                if alerts:
                    print(f"     ⚠️  {', '.join(alerts)}")

            else:
                print(f"❌ [{counter:03d}] Lỗi gửi dữ liệu")

            counter += 1
            time.sleep(5)  # Gửi mỗi 5 giây

    except KeyboardInterrupt:
        print("\n🛑 Dừng test...")
    except Exception as e:
        print(f"❌ Lỗi: {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        print("👋 Đã ngắt kết nối MQTT")


if __name__ == "__main__":
    main()
