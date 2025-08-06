import paho.mqtt.client as mqtt
import json
import time
import random
from datetime import datetime

# MQTT Configuration
MQTT_BROKER = "localhost"  
MQTT_PORT = 1883
MQTT_TOPIC = "sensor/tvoc"

def generate_fake_data():
    """Generate fake sensor data"""
    return {
        "tvoc": random.uniform(100, 1000),  # ppb
        "temperature": random.uniform(15, 40),  # °C
        "humidity": random.uniform(20, 80),  # %
        "eco2": random.uniform(300, 1500),  # ppm
        "aqi": random.randint(1, 5),  # 1-5 scale
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

def main():
    # Create MQTT client
    client = mqtt.Client()
    
    try:
        # Connect to MQTT broker
        print(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        print("Connected!")

        while True:
            # Generate and send data
            data = generate_fake_data()
            message = json.dumps(data)
            client.publish(MQTT_TOPIC, message)
            
            print(f"""
Sent data:
- TVOC: {data['tvoc']:.2f} ppb
- Temperature: {data['temperature']:.1f}°C
- Humidity: {data['humidity']:.1f}%
- eCO2: {data['eco2']:.0f} ppm
- AQI: {data['aqi']}
            """)
            
            # Wait 2 seconds before sending next data
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopping data generation...")
        client.disconnect()
        print("Disconnected from MQTT broker")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
