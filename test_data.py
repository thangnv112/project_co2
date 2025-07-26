#!/usr/bin/env python3
"""
Script test gửi dữ liệu giả để test hệ thống
Chạy song song với server.py để xem dashboard hoạt động
"""

import paho.mqtt.client as mqtt
import json
import time
import random
from datetime import datetime

# Cấu hình MQTT
MQTT_BROKER = 'localhost'
MQTT_PORT = 1883
MQTT_TOPIC = 'sensors/data'

def generate_fake_data():
    """Tạo dữ liệu cảm biến giả"""
    # CO2: dao động từ 400-1500 ppm
    co2 = random.uniform(400, 1500)
    
    # Nhiệt độ: dao động từ 20-35°C
    temperature = random.uniform(20, 35)
    
    # Độ ẩm: dao động từ 30-80%
    humidity = random.uniform(30, 80)
    
    # Tạo một số tình huống đặc biệt
    scenario = random.randint(1, 10)
    
    if scenario == 1:  # CO2 cao
        co2 = random.uniform(1000, 2000)
    elif scenario == 2:  # Nhiệt độ cao
        temperature = random.uniform(32, 40)
    elif scenario == 3:  # Độ ẩm cao
        humidity = random.uniform(75, 90)
    
    return {
        'co2': round(co2, 1),
        'temperature': round(temperature, 1),
        'humidity': round(humidity, 1),
        'timestamp': datetime.now().isoformat()
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
            
            # Gửi qua MQTT
            result = client.publish(MQTT_TOPIC, json_data)
            
            if result.rc == 0:
                print(f"📤 [{counter:03d}] Sent: CO2={data['co2']}ppm, T={data['temperature']}°C, H={data['humidity']}%")
                
                # Hiển thị cảnh báo nếu có
                alerts = []
                if data['co2'] > 1000:
                    alerts.append(f"🚨 CO2 cao ({data['co2']}ppm)")
                if data['temperature'] > 30:
                    alerts.append(f"🔥 Nhiệt độ cao ({data['temperature']}°C)")
                if data['humidity'] > 70:
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