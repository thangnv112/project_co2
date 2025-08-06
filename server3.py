#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVOC Monitoring Server for Raspberry Pi 5
Handles MQTT, Database, Telegram alerts, and Web Dashboard
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

import mariadb
import paho.mqtt.client as mqtt
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request
from flask_socketio import SocketIO, emit

from config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    FLASK_SECRET_KEY,
    MQTT_BROKER,
    MQTT_PORT,
    MQTT_TOPIC,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

# Load .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*")

# Database configuration
DB_CONFIG = {
    "host": DB_HOST,
    "port": DB_PORT,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "database": DB_NAME,
}

# Default thresholds for TVOC
DEFAULT_THRESHOLDS = {
    "tvoc_max": 660,  # ppb
    "temp_min": 18,
    "temp_max": 35,
    "humidity_min": 30,
    "humidity_max": 70,
    "eco2_min": 400,  # ppm
    "eco2_max": 1000,  # ppm
}

# Global variables for data storage
current_data = {
    "tvoc": 0,
    "temperature": 0,
    "humidity": 0,
    "eco2": 0,
    "aqi": 1,
    "timestamp": datetime.now(),
}

thresholds = DEFAULT_THRESHOLDS.copy()
last_alert_time = {}


class DatabaseManager:
    """Database manager class for handling MariaDB operations"""

    def __init__(self):
        self.connection = None
        self.connect()
        self.create_tables()

    def connect(self):
        """Establish database connection"""
        try:
            self.connection = mariadb.connect(**DB_CONFIG)
            logger.info("Database connection successful")
        except Exception as e:
            logger.error(f"Database connection error: {e}")

    def create_tables(self):
        """Create necessary database tables"""
        try:
            cursor = self.connection.cursor()

            # Sensor data table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_data (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    tvoc FLOAT NOT NULL,
                    temperature FLOAT NOT NULL,
                    humidity FLOAT NOT NULL,
                    eco2 FLOAT NOT NULL,
                    aqi INT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Thresholds table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS thresholds (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    tvoc_max FLOAT DEFAULT 70,
                    temp_min FLOAT DEFAULT 18,
                    temp_max FLOAT DEFAULT 30,
                    humidity_min FLOAT DEFAULT 30,
                    humidity_max FLOAT DEFAULT 70,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Alert history table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    alert_type VARCHAR(50) NOT NULL,
                    message TEXT NOT NULL,
                    value FLOAT NOT NULL,
                    threshold_value FLOAT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            self.connection.commit()
            logger.info("Database tables created successfully")

        except Exception as e:
            logger.error(f"Error creating tables: {e}")

    def insert_sensor_data(self, tvoc, temperature, humidity, eco2, aqi):
        """Insert sensor data into database"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO sensor_data (tvoc, temperature, humidity, eco2, aqi) VALUES (?, ?, ?, ?, ?)",
                (tvoc, temperature, humidity, eco2, aqi),
            )
            self.connection.commit()
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            self.connect()  # Try to reconnect

    def get_recent_data(self, hours=24):
        """Get recent sensor data from database"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT tvoc, temperature, humidity, eco2, aqi, timestamp 
                FROM sensor_data 
                WHERE timestamp >= NOW() - INTERVAL ? HOUR 
                ORDER BY timestamp ASC
            """,
                (hours,),
            )

            data = []
            for row in cursor.fetchall():
                data.append(
                    {
                        "tvoc": row[0],
                        "temperature": row[1],
                        "humidity": row[2],
                        "eco2": row[3],
                        "aqi": row[4],
                        "timestamp": row[5].strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            return data
        except Exception as e:
            logger.error(f"Error reading data: {e}")
            return []

    def update_thresholds(self, new_thresholds):
        """Update threshold values in database"""
        try:
            cursor = self.connection.cursor()
            # Check if record exists
            cursor.execute("SELECT id FROM thresholds LIMIT 1")
            row = cursor.fetchone()

            if row:
                # Update existing record
                cursor.execute(
                    """
                    UPDATE thresholds 
                    SET tvoc_max=?, temp_min=?, temp_max=?, 
                        humidity_min=?, humidity_max=?, 
                        eco2_min=?, eco2_max=?,
                        updated_at=CURRENT_TIMESTAMP 
                    WHERE id=?
                """,
                    (
                        new_thresholds["tvoc_max"],
                        new_thresholds["temp_min"],
                        new_thresholds["temp_max"],
                        new_thresholds["humidity_min"],
                        new_thresholds["humidity_max"],
                        new_thresholds["eco2_min"],
                        new_thresholds["eco2_max"],
                        row[0],
                    ),
                )
            else:
                # Insert new record
                cursor.execute(
                    """
                    INSERT INTO thresholds (
                        tvoc_max, temp_min, temp_max, 
                        humidity_min, humidity_max,
                        eco2_min, eco2_max
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        new_thresholds["tvoc_max"],
                        new_thresholds["temp_min"],
                        new_thresholds["temp_max"],
                        new_thresholds["humidity_min"],
                        new_thresholds["humidity_max"],
                        new_thresholds["eco2_min"],
                        new_thresholds["eco2_max"],
                    ),
                )

            self.connection.commit()
            logger.info("Thresholds updated successfully")
        except Exception as e:
            logger.error(f"Error updating thresholds: {e}")

    def log_alert(self, alert_type, message, value, threshold_value):
        """Log alert to database"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO alert_history (alert_type, message, value, threshold_value)
                VALUES (?, ?, ?, ?)
            """,
                (alert_type, message, value, threshold_value),
            )
            self.connection.commit()
        except Exception as e:
            logger.error(f"Error logging alert: {e}")


# Initialize Database Manager
db = DatabaseManager()


def send_telegram_alert(message):
    """Send alert via Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🚨 CẢNH BÁO 🚨\n\n{message}",
            "parse_mode": "HTML",
        }
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram message sent successfully")
        else:
            logger.error(f"Telegram error: {response.status_code}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")


def check_thresholds_and_alert(tvoc, temperature, humidity, eco2):
    """Check thresholds and send alerts for TVOC, temperature, humidity and eCO2"""
    global last_alert_time
    current_time = datetime.now()
    alerts = []

    # Check TVOC
    if tvoc > thresholds["tvoc_max"]:
        alert_key = "tvoc_high"
        if (
            alert_key not in last_alert_time
            or (current_time - last_alert_time[alert_key]).seconds > 300
        ):  # 5 minutes

            message = (
                f"⚠️ TVOC quá cao: {tvoc:.2f} ppb "
                f"(Ngưỡng: {thresholds['tvoc_max']:.2f} ppb)\n"
                "💨 Khuyến nghị: Mở cửa sổ hoặc tăng thông gió!"
            )

            send_telegram_alert(message)
            db.log_alert("tvoc_high", message, tvoc, thresholds["tvoc_max"])
            last_alert_time[alert_key] = current_time

            alerts.append(
                {
                    "type": "tvoc_high",
                    "message": f"TVOC cao: {tvoc:.2f} ppb",
                    "severity": "danger",
                }
            )

    # Check temperature
    if temperature < thresholds["temp_min"] or temperature > thresholds["temp_max"]:
        alert_key = "temp_abnormal"
        if (
            alert_key not in last_alert_time
            or (current_time - last_alert_time[alert_key]).seconds > 600
        ):  # 10 minutes

            if temperature < thresholds["temp_min"]:
                message = (
                    f"🥶 Nhiệt độ quá thấp: {temperature}°C "
                    f"(Tối thiểu: {thresholds['temp_min']}°C)"
                )
            else:
                message = (
                    f"🥵 Nhiệt độ quá cao: {temperature}°C "
                    f"(Tối đa: {thresholds['temp_max']}°C)"
                )

            send_telegram_alert(message)
            db.log_alert(
                "temp_abnormal",
                message,
                temperature,
                (
                    thresholds["temp_min"]
                    if temperature < thresholds["temp_min"]
                    else thresholds["temp_max"]
                ),
            )
            last_alert_time[alert_key] = current_time

            alerts.append(
                {
                    "type": "temp_abnormal",
                    "message": f"Nhiệt độ bất thường: {temperature}°C",
                    "severity": "warning",
                }
            )

    # Check humidity
    if humidity < thresholds["humidity_min"] or humidity > thresholds["humidity_max"]:
        alert_key = "humidity_abnormal"
        if (
            alert_key not in last_alert_time
            or (current_time - last_alert_time[alert_key]).seconds > 600
        ):  # 10 minutes

            if humidity < thresholds["humidity_min"]:
                message = (
                    f"🏜️ Độ ẩm quá thấp: {humidity}% "
                    f"(Tối thiểu: {thresholds['humidity_min']}%)"
                )
            else:
                message = (
                    f"💧 Độ ẩm quá cao: {humidity}% "
                    f"(Tối đa: {thresholds['humidity_max']}%)"
                )

            send_telegram_alert(message)
            db.log_alert(
                "humidity_abnormal",
                message,
                humidity,
                (
                    thresholds["humidity_min"]
                    if humidity < thresholds["humidity_min"]
                    else thresholds["humidity_max"]
                ),
            )
            last_alert_time[alert_key] = current_time

            alerts.append(
                {
                    "type": "humidity_abnormal",
                    "message": f"Độ ẩm bất thường: {humidity}%",
                    "severity": "warning",
                }
            )

    # Check eCO2
    if eco2 < thresholds["eco2_min"] or eco2 > thresholds["eco2_max"]:
        alert_key = "eco2_abnormal"
        if (
            alert_key not in last_alert_time
            or (current_time - last_alert_time[alert_key]).seconds > 600
        ):  # 10 minutes

            if eco2 < thresholds["eco2_min"]:
                message = (
                    f"🌿 Nồng độ CO2 quá thấp: {eco2} ppm "
                    f"(Tối thiểu: {thresholds['eco2_min']} ppm)"
                )
            else:
                message = (
                    f"⚠️ Nồng độ CO2 quá cao: {eco2} ppm "
                    f"(Tối đa: {thresholds['eco2_max']} ppm)\n"
                    "💨 Khuyến nghị: Mở cửa sổ hoặc tăng thông gió!"
                )

            send_telegram_alert(message)
            db.log_alert(
                "eco2_abnormal",
                message,
                eco2,
                (
                    thresholds["eco2_min"]
                    if eco2 < thresholds["eco2_min"]
                    else thresholds["eco2_max"]
                ),
            )
            last_alert_time[alert_key] = current_time

            alerts.append(
                {
                    "type": "eco2_abnormal",
                    "message": f"Nồng độ CO2 bất thường: {eco2} ppm",
                    "severity": (
                        "warning" if eco2 < thresholds["eco2_min"] else "danger"
                    ),
                }
            )

    return alerts


# MQTT Client functions
def on_connect(client, userdata, flags, rc):
    """MQTT connection callback"""
    if rc == 0:
        logger.info("MQTT connection successful")
        client.subscribe(MQTT_TOPIC)
    else:
        logger.error(f"MQTT connection error: {rc}")


def on_message(client, userdata, msg):
    """MQTT message callback"""
    try:
        data = json.loads(msg.payload.decode())

        tvoc = float(data.get("tvoc", data.get("TVOC", 0)))
        temperature = float(data.get("temperature", data.get("Temperature", 0)))
        humidity = float(data.get("humidity", data.get("Humidity", 0)))
        eco2 = float(data.get("eco2", data.get("eCO2", 0)))
        aqi = int(data.get("aqi", data.get("AQI", 1)))

        # Update current data
        current_data.update(
            {
                "tvoc": tvoc,
                "temperature": temperature,
                "humidity": humidity,
                "eco2": eco2,
                "aqi": aqi,
                "timestamp": datetime.now(),
            }
        )

        # Save to database
        db.insert_sensor_data(tvoc, temperature, humidity, eco2, aqi)

        # Check thresholds and alert
        alerts = check_thresholds_and_alert(tvoc, temperature, humidity, eco2)

        # Send real-time data via WebSocket
        socketio.emit(
            "sensor_data",
            {
                "tvoc": tvoc,
                "temperature": temperature,
                "humidity": humidity,
                "eco2": eco2,
                "timestamp": current_data["timestamp"].strftime("%H:%M:%S"),
                "alerts": alerts,
            },
        )

        logger.info(
            f"Received data: TVOC={tvoc:.2f}ppb, T={temperature}°C, "
            f"H={humidity}%, eCO2={eco2}ppm"
        )

    except Exception as e:
        logger.error(f"MQTT processing error: {e}")


# Initialize MQTT Client
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message


def start_mqtt():
    """Start MQTT client"""
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_forever()
    except Exception as e:
        logger.error(f"MQTT error: {e}")


# HTML Template (inline)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>🌱 Smart Indoor Air Quality Monitoring Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.0/socket.io.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        /* AQI Status Styles */
        .aqi-excellent {
            background: linear-gradient(45deg, #4CAF50, #45a049) !important;
            color: white !important;
        }
        .aqi-good {
            background: linear-gradient(45deg, #8BC34A, #7CB342) !important;
            color: white !important;
        }
        .aqi-average {
            background: linear-gradient(45deg, #FFC107, #FFB300) !important;
            color: white !important;
        }
        .aqi-poor {
            background: linear-gradient(45deg, #FF9800, #F57C00) !important;
            color: white !important;
        }
        .aqi-very-poor {
            background: linear-gradient(45deg, #f44336, #d32f2f) !important;
            color: white !important;
        }
        
        /* Base Styles */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }

        .header {
            text-align: center;
            margin-bottom: 30px;
            color: white;
        }

        .header h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
        }

        .header p {
            font-size: 1.1rem;
            opacity: 0.9;
        }

        .status-bar {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 15px;
            margin-bottom: 25px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: white;
            text-align: center;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
            max-width: 1400px;
            margin-left: auto;
            margin-right: auto;
        }

        @media (max-width: 1200px) {
            #thresholdForm {
                grid-template-columns: repeat(2, 1fr) !important;
            }
        }

        @media (max-width: 768px) {
            #thresholdForm {
                grid-template-columns: 1fr !important;
            }
        }

        .sensors-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 30px;
            max-width: 1400px;
            margin-left: auto;
            margin-right: auto;
        }

        @media (max-width: 1200px) {
            .sensors-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }

        @media (max-width: 768px) {
            .sensors-grid {
                grid-template-columns: 1fr;
            }
        }

        .card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }

        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
        }

        .card h3 {
            color: #444;
            margin-bottom: 15px;
            font-size: 1.3rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .sensor-card {
            text-align: center;
        }

        .sensor-value {
            font-size: 3rem;
            font-weight: bold;
            margin: 15px 0;
            text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.1);
        }

        .sensor-unit {
            font-size: 1.2rem;
            color: #666;
            margin-left: 5px;
        }

        .sensor-status {
            padding: 8px 16px;
            border-radius: 25px;
            font-weight: bold;
            text-transform: uppercase;
            font-size: 0.9rem;
            display: inline-block;
            margin-top: 10px;
        }

        .status-normal {
            background: linear-gradient(45deg, #4caf50, #45a049);
            color: white;
        }

        .status-warning {
            background: linear-gradient(45deg, #ff9800, #f57c00);
            color: white;
        }

        .status-danger {
            background: linear-gradient(45deg, #f44336, #d32f2f);
            color: white;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.05); }
            100% { transform: scale(1); }
        }

        .tvoc-card { border-left: 5px solid #ff6b6b; }
        .temp-card { border-left: 5px solid #4ecdc4; }
        .humidity-card { border-left: 5px solid #45b7d1; }

        .chart-container {
            position: relative;
            height: 400px;
            margin-top: 20px;
        }

        .controls-card {
            grid-column: 1 / -1;
        }

        .form-group {
            margin-bottom: 20px;
        }

        .form-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 15px;
        }

        .form-control {
            display: flex;
            flex-direction: column;
        }

        .form-control label {
            font-weight: 600;
            margin-bottom: 5px;
            color: #555;
        }

        .form-control input {
            padding: 12px 15px;
            border: 2px solid #e1e5e9;
            border-radius: 10px;
            font-size: 1rem;
            transition: border-color 0.3s ease, box-shadow 0.3s ease;
            background: rgba(255, 255, 255, 0.8);
        }

        .form-control input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .btn {
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 25px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }

        .btn:active {
            transform: translateY(0);
        }

        .alerts {
            margin-top: 20px;
        }

        .alert {
            padding: 15px 20px;
            border-radius: 10px;
            margin-bottom: 10px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 10px;
            animation: slideIn 0.5s ease;
        }

        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateX(-20px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }

        .alert-danger {
            background: linear-gradient(45deg, #ff6b6b, #ee5a52);
            color: white;
        }

        .alert-warning {
            background: linear-gradient(45deg, #ffa726, #fb8c00);
            color: white;
        }

        .last-update {
            text-align: center;
            color: rgba(255, 255, 255, 0.8);
            font-size: 0.9rem;
            margin-top: 10px;
        }

        .icon {
            font-size: 1.5rem;
        }

        .connection-status {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 10px 15px;
            border-radius: 25px;
            font-size: 0.9rem;
            font-weight: 600;
            z-index: 1000;
        }

        .connected {
            background: #4caf50;
            color: white;
        }

        .disconnected {
            background: #f44336;
            color: white;
            animation: pulse 1s infinite;
        }

        .success-message {
            background: #4caf50;
            color: white;
            padding: 10px 20px;
            border-radius: 10px;
            margin: 10px 0;
            display: none;
        }
    </style>
</head>
<body>
    <div class="connection-status" id="connectionStatus">
        🔴 Đang kết nối...
    </div>

    <div class="container">
        <div class="header">
            <h1>🌱 Smart Indoor Air Quality Monitoring Dashboard</h1>
            <p>Giám sát chất lượng không khí trong phòng kín</p>
        </div>

        <div class="status-bar" id="statusBar">
            <div id="lastUpdate">Đang tải dữ liệu...</div>
        </div>

        <div class="sensors-grid">
            <!-- TVOC Card -->
            <div class="card sensor-card tvoc-card">
                <h3><span class="icon">💨</span> Nồng độ TVOC</h3>
                <div class="sensor-value" id="tvocValue">
                    0<span class="sensor-unit">ppb</span>
                </div>
                <div class="sensor-status status-normal" id="tvocStatus">
                    Bình thường
                </div>
            </div>

            <!-- Temperature Card -->
            <div class="card sensor-card temp-card">
                <h3><span class="icon">🌡️</span> Nhiệt độ</h3>
                <div class="sensor-value" id="tempValue">
                    0<span class="sensor-unit">°C</span>
                </div>
                <div class="sensor-status status-normal" id="tempStatus">
                    Bình thường
                </div>
            </div>

            <!-- Humidity Card -->
            <div class="card sensor-card humidity-card">
                <h3><span class="icon">💧</span> Độ ẩm</h3>
                <div class="sensor-value" id="humidityValue">
                    0<span class="sensor-unit">%</span>
                </div>
                <div class="sensor-status status-normal" id="humidityStatus">
                    Bình thường
                </div>
            </div>

            <!-- eCO2 Card -->
            <div class="card sensor-card eco2-card" style="border-left: 5px solid #9CCC65;">
                <h3><span class="icon">🌿</span> Nồng độ eCO2</h3>
                <div class="sensor-value" id="eco2Value">
                    0<span class="sensor-unit">ppm</span>
                </div>
                <div class="sensor-status status-normal" id="eco2Status">
                    Bình thường
                </div>
            </div>

            <!-- AQI Card -->
            <div class="card sensor-card aqi-card" style="grid-column: 1 / -1; margin-top: 20px;">
                <h3><span class="icon">👁️</span> Chỉ số AQI</h3>
                <div class="sensor-status" id="aqiStatus" style="font-size: 1.5rem; padding: 15px 30px; margin: 15px 0;">
                    Excellent
                </div>
            </div>
        </div>

        <div class="grid">
            <!-- Chart Card -->
            <div class="card" style="grid-column: 1 / -1">
                <h3><span class="icon">📊</span> Biểu đồ theo thời gian</h3>
                <div class="chart-container">
                    <canvas id="sensorChart"></canvas>
                </div>
            </div>

            <!-- Controls Card -->
            <form id="thresholdForm" style="
                width: 100%;
                grid-column: 1 / -1;
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 20px;
            ">
                <div class="card tvoc-card">
                    <h3><span class="icon">💨</span> Cài đặt ngưỡng TVOC</h3>
                    <div class="form-group">
                        <div class="form-control">
                            <label for="tvocMax">TVOC tối đa (ppb)</label>
                            <input type="number" id="tvocMax" name="tvoc_max" value="70" 
                                   min="0" max="1000" step="10" />
                        </div>
                    </div>
                </div>

                <!-- Temperature Threshold Card -->
                <div class="card temp-card">
                    <h3><span class="icon">🌡️</span> Cài đặt ngưỡng Nhiệt độ</h3>
                    <div class="form-row">
                        <div class="form-control">
                            <label for="tempMin">Nhiệt độ tối thiểu (°C)</label>
                            <input type="number" id="tempMin" name="temp_min" value="18" 
                                   min="0" max="50" step="1" />
                        </div>
                        <div class="form-control">
                            <label for="tempMax">Nhiệt độ tối đa (°C)</label>
                            <input type="number" id="tempMax" name="temp_max" value="30" 
                                   min="0" max="50" step="1" />
                        </div>
                    </div>
                </div>

                <!-- Humidity Threshold Card -->
                <div class="card humidity-card">
                    <h3><span class="icon">💧</span> Cài đặt ngưỡng Độ ẩm</h3>
                    <div class="form-row">
                        <div class="form-control">
                            <label for="humidityMin">Độ ẩm tối thiểu (%)</label>
                            <input type="number" id="humidityMin" name="humidity_min" value="30" 
                                   min="0" max="100" step="5" />
                        </div>
                        <div class="form-control">
                            <label for="humidityMax">Độ ẩm tối đa (%)</label>
                            <input type="number" id="humidityMax" name="humidity_max" value="70" 
                                   min="0" max="100" step="5" />
                        </div>
                    </div>
                </div>

                <!-- eCO2 Threshold Card -->
                <div class="card eco2-card" style="border-left: 5px solid #9CCC65;">
                    <h3><span class="icon">🌿</span> Cài đặt ngưỡng eCO2</h3>
                    <div class="form-row">
                        <div class="form-control">
                            <label for="eco2Min">eCO2 tối thiểu (ppm)</label>
                            <input type="number" id="eco2Min" name="eco2_min" value="400" 
                                   min="0" max="5000" step="50" />
                        </div>
                        <div class="form-control">
                            <label for="eco2Max">eCO2 tối đa (ppm)</label>
                            <input type="number" id="eco2Max" name="eco2_max" value="1000" 
                                   min="0" max="5000" step="50" />
                        </div>
                    </div>
                </div>

                <!-- Submit Button -->
                <div style="text-align: center; grid-column: 1 / -1">
                    <button type="submit" class="btn" 
                            style="background: linear-gradient(45deg, #2196f3, #1976d2)">
                        💾 Cập nhật ngưỡng
                    </button>
                    <div class="success-message" id="successMessage" style="margin-top: 10px">
                        ✅ Cập nhật ngưỡng thành công!
                    </div>
                </div>
            </form>
        </div>

        <!-- Alerts -->
        <div id="alertsContainer" class="alerts"></div>
    </div>

    <script>
        // Initialize global variables
        let socket;
        let sensorChart;
        let chartData = {
            labels: [],
            tvocData: [],
            tempData: [],
            humidityData: [],
            eco2Data: [],
        };

        // Initialize when page loads
        document.addEventListener("DOMContentLoaded", function () {
            console.log("🚀 Initializing dashboard...");
            initializeSocket();
            initializeChart();
            loadInitialData();
            setupThresholdForm();
        });

        // Initialize Socket.IO
        function initializeSocket() {
            socket = io();

            // Connection successful
            socket.on("connect", function () {
                console.log("✅ Socket.IO connection successful");
                updateConnectionStatus(true);
            });

            // Connection lost
            socket.on("disconnect", function () {
                console.log("❌ Socket.IO connection lost");
                updateConnectionStatus(false);
            });

            // Receive real-time sensor data
            socket.on("sensor_data", function (data) {
                console.log("📊 Received sensor data:", data);
                updateSensorDisplay(data);
                updateChart(data);
                showAlerts(data.alerts || []);
            });

            // Receive threshold update notifications
            socket.on("thresholds_updated", function (thresholds) {
                console.log("⚙️ Thresholds updated:", thresholds);
                updateThresholdForm(thresholds);
            });
        }

        // Update connection status
        function updateConnectionStatus(connected) {
            const statusEl = document.getElementById("connectionStatus");
            if (connected) {
                statusEl.textContent = "🟢 Đã kết nối";
                statusEl.className = "connection-status connected";
            } else {
                statusEl.textContent = "🔴 Mất kết nối";
                statusEl.className = "connection-status disconnected";
            }
        }

        // Update sensor display
        function updateSensorDisplay(data) {
            // Update values
            document.getElementById("tvocValue").innerHTML = 
                `${data.tvoc.toFixed(2)}<span class="sensor-unit">ppb</span>`;
            document.getElementById("tempValue").innerHTML = 
                `${data.temperature}<span class="sensor-unit">°C</span>`;
            document.getElementById("humidityValue").innerHTML = 
                `${data.humidity}<span class="sensor-unit">%</span>`;
            document.getElementById("eco2Value").innerHTML = 
                `${data.eco2}<span class="sensor-unit">ppm</span>`;

            // Update status
            updateSensorStatus("tvoc", data.tvoc);
            updateSensorStatus("temp", data.temperature);
            updateSensorStatus("humidity", data.humidity);
            updateSensorStatus("eco2", data.eco2);
            
            if (data.aqi) {
                updateAQIStatus(data.aqi);
            }
            
            // Update timestamp
            document.getElementById("lastUpdate").textContent = 
                `Cập nhật lần cuối: ${data.timestamp}`;
        }

        function updateAQIStatus(aqi) {
            const statusEl = document.getElementById('aqiStatus');
            let className = '';
            let text = '';
            
            switch(aqi) {
                case 1:
                    className = 'aqi-excellent';
                    text = 'Excellent';
                    break;
                case 2:
                    className = 'aqi-good';
                    text = 'Good';
                    break;
                case 3:
                    className = 'aqi-average';
                    text = 'Average';
                    break;
                case 4:
                    className = 'aqi-poor';
                    text = 'Poor';
                    break;
                case 5:
                    className = 'aqi-very-poor';
                    text = 'Very Poor';
                    break;
                default:
                    className = 'aqi-excellent';
                    text = 'Excellent';
            }
            
            statusEl.className = `sensor-status ${className}`;
            statusEl.textContent = text;
        }
        
        // Update sensor status
        function updateSensorStatus(sensorType, value) {
            const statusEl = document.getElementById(
                sensorType === "temp" ? "tempStatus" : sensorType + "Status"
            );

            let status = "status-normal";
            let text = "Bình thường";

            if (sensorType === "tvoc" && value > 660) {
                status = "status-danger";
                text = "Quá cao";
            } else if (sensorType === "temp" && (value < 18 || value > 30)) {
                status = "status-warning";
                text = "Bất thường";
            } else if (sensorType === "humidity" && (value < 30 || value > 70)) {
                status = "status-warning";
                text = "Bất thường";
            }

            statusEl.className = `sensor-status ${status}`;
            statusEl.textContent = text;
        }

        // Initialize chart
        function initializeChart() {
            const ctx = document.getElementById("sensorChart").getContext("2d");
            console.log("📊 Initializing chart...");

            sensorChart = new Chart(ctx, {
                type: "line",
                data: {
                    labels: chartData.labels,
                    datasets: [
                        {
                            label: "TVOC (ppb)",
                            data: chartData.tvocData,
                            borderColor: "#FF6B6B",
                            backgroundColor: "rgba(255, 107, 107, 0.1)",
                            tension: 0.4,
                            yAxisID: "y",
                            fill: false,
                        },
                        {
                            label: "Nhiệt độ (°C)",
                            data: chartData.tempData,
                            borderColor: "#4ECDC4",
                            backgroundColor: "rgba(78, 205, 196, 0.1)",
                            tension: 0.4,
                            yAxisID: "y1",
                            fill: false,
                        },
                        {
                            label: "Độ ẩm (%)",
                            data: chartData.humidityData,
                            borderColor: "#45B7D1",
                            backgroundColor: "rgba(69, 183, 209, 0.1)",
                            tension: 0.4,
                            yAxisID: "y1",
                            fill: false,
                        },
                        {
                            label: "eCO2 (ppm)",
                            data: chartData.eco2Data,
                            borderColor: "#9CCC65",
                            backgroundColor: "rgba(156, 204, 101, 0.1)",
                            tension: 0.4,
                            yAxisID: "y2",
                            fill: false,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        intersect: false,
                        mode: "index",
                    },
                    scales: {
                        x: {
                            display: true,
                            title: {
                                display: true,
                                text: "Thời gian",
                                color: "#666",
                            },
                            grid: {
                                color: "rgba(0,0,0,0.1)",
                            },
                        },
                        y: {
                            type: "linear",
                            display: true,
                            position: "left",
                            title: {
                                display: true,
                                text: "TVOC (ppb)",
                                color: "#FF6B6B",
                            },
                            grid: {
                                color: "rgba(255, 107, 107, 0.1)",
                            },
                            min: 0,
                            max: 2,
                        },
                        y1: {
                            type: "linear",
                            display: true,
                            position: "right",
                            title: {
                                display: true,
                                text: "Nhiệt độ (°C) / Độ ẩm (%)",
                                color: "#4ECDC4",
                            },
                            grid: {
                                drawOnChartArea: false,
                                color: "rgba(78, 205, 196, 0.1)",
                            },
                            min: 0,
                            max: 100,
                        },
                        y2: {
                            type: "linear",
                            display: true,
                            position: "right",
                            title: {
                                display: true,
                                text: "eCO2 (ppm)",
                                color: "#9CCC65",
                            },
                            grid: {
                                drawOnChartArea: false,
                                color: "rgba(156, 204, 101, 0.1)",
                            },
                            min: 0,
                            max: 2000,
                        },
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: "top",
                            labels: {
                                color: "#333",
                                usePointStyle: true,
                                padding: 20,
                            },
                        },
                        tooltip: {
                            backgroundColor: "rgba(0,0,0,0.8)",
                            titleColor: "white",
                            bodyColor: "white",
                            borderColor: "rgba(255,255,255,0.2)",
                            borderWidth: 1,
                        },
                    },
                    animation: {
                        duration: 750,
                    },
                },
            });

            console.log("✅ Chart initialized successfully");
        }

        // Update chart with real-time data
        function updateChart(data) {
            const now = data.timestamp || new Date().toLocaleTimeString();

            // Add new data
            chartData.labels.push(now);
            chartData.tvocData.push(data.tvoc);
            chartData.tempData.push(data.temperature);
            chartData.humidityData.push(data.humidity);
            chartData.eco2Data.push(data.eco2);

            // Limit number of displayed points (last 10 points)
            if (chartData.labels.length > 10) {
                console.log("Data limit reached, removing old point:", chartData.labels.length);
                chartData.labels.shift();
                chartData.tvocData.shift();
                chartData.tempData.shift();
                chartData.humidityData.shift();
                chartData.eco2Data.shift();
            }

            // Update chart data
            sensorChart.data.labels = chartData.labels;
            sensorChart.data.datasets[0].data = chartData.tvocData;
            sensorChart.data.datasets[1].data = chartData.tempData;
            sensorChart.data.datasets[2].data = chartData.humidityData;
            sensorChart.data.datasets[3].data = chartData.eco2Data;

            // Update chart with smooth animation
            sensorChart.update("active");

            console.log("📈 Chart updated:", {
                time: now,
                tvoc: data.tvoc,
                temp: data.temperature,
                humidity: data.humidity,
            });
        }

        // Load initial data
        function loadInitialData() {
            // Load current data
            fetch("/api/current-data")
                .then((response) => response.json())
                .then((data) => {
                    console.log("📥 Current data:", data);
                    updateSensorDisplay({
                        tvoc: data.tvoc,
                        temperature: data.temperature,
                        humidity: data.humidity,
                        eco2: data.eco2,
                        timestamp: new Date(data.timestamp).toLocaleTimeString(),
                    });

                    // Update threshold form
                    if (data.thresholds) {
                        updateThresholdForm(data.thresholds);
                    }
                })
                .catch((error) => {
                    console.error("❌ Error loading current data:", error);
                });

            // Load historical data for chart
            fetch("/api/history?hours=1")
                .then((response) => response.json())
                .then((data) => {
                    console.log("📈 Historical data:", data);

                    // Reset chart data
                    chartData.labels = [];
                    chartData.tvocData = [];
                    chartData.tempData = [];
                    chartData.humidityData = [];
                    chartData.eco2Data = [];

                    // If historical data exists, add to chart
                    if (data && data.length > 0) {
                        const recentData = data.slice(-5); // Take only last 5 points
                        recentData.forEach((item) => {
                            const time = new Date(item.timestamp).toLocaleTimeString();
                            chartData.labels.push(time);
                            chartData.tvocData.push(item.tvoc);
                            chartData.tempData.push(item.temperature);
                            chartData.humidityData.push(item.humidity);
                            chartData.eco2Data.push(item.eco2);
                        });
                    } else {
                        // If no historical data, create default point
                        const now = new Date().toLocaleTimeString();
                        chartData.labels.push(now);
                        chartData.tvocData.push(0);
                        chartData.tempData.push(25);
                        chartData.humidityData.push(50);
                        chartData.eco2Data.push(400);
                    }

                    // Update chart
                    sensorChart.data.labels = chartData.labels;
                    sensorChart.data.datasets[0].data = chartData.tvocData;
                    sensorChart.data.datasets[1].data = chartData.tempData;
                    sensorChart.data.datasets[2].data = chartData.humidityData;
                    sensorChart.data.datasets[3].data = chartData.eco2Data;
                    sensorChart.update();
                })
                .catch((error) => {
                    console.error("❌ Error loading historical data:", error);
                    // Create default data if error
                    const now = new Date().toLocaleTimeString();
                    chartData.labels = [now];
                    chartData.tvocData = [0];
                    chartData.tempData = [25];
                    chartData.humidityData = [50];
                    chartData.eco2Data = [400];

                    sensorChart.data.labels = chartData.labels;
                    sensorChart.data.datasets[0].data = chartData.tvocData;
                    sensorChart.data.datasets[1].data = chartData.tempData;
                    sensorChart.data.datasets[2].data = chartData.humidityData;
                    sensorChart.data.datasets[3].data = chartData.eco2Data;
                    sensorChart.update();
                });
        }

        // Setup threshold form
        function setupThresholdForm() {
            const form = document.getElementById("thresholdForm");

            form.addEventListener("submit", function (e) {
                e.preventDefault(); // Prevent default form submit
                console.log("📝 Updating thresholds...");

                // Get form data
                const formData = {
                    tvoc_max: parseFloat(document.getElementById("tvocMax").value),
                    temp_min: parseFloat(document.getElementById("tempMin").value),
                    temp_max: parseFloat(document.getElementById("tempMax").value),
                    humidity_min: parseFloat(document.getElementById("humidityMin").value),
                    humidity_max: parseFloat(document.getElementById("humidityMax").value),
                    eco2_min: parseFloat(document.getElementById("eco2Min").value),
                    eco2_max: parseFloat(document.getElementById("eco2Max").value),
                };

                console.log("📤 Sending data:", formData);

                // Send POST request
                fetch("/api/thresholds", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(formData),
                })
                    .then((response) => response.json())
                    .then((data) => {
                        console.log("✅ Update successful:", data);

                        if (data.success) {
                            // Show success message
                            showSuccessMessage();

                            // Update form with new data
                            updateThresholdForm(data.thresholds);
                        } else {
                            console.error("❌ Update error:", data.error);
                            alert("Lỗi cập nhật ngưỡng: " + data.error);
                        }
                    })
                    .catch((error) => {
                        console.error("❌ Connection error:", error);
                        alert("Lỗi kết nối khi cập nhật ngưỡng");
                    });
            });
        }

        // Update threshold form
        function updateThresholdForm(thresholds) {
            document.getElementById("tvocMax").value = thresholds.tvoc_max;
            document.getElementById("tempMin").value = thresholds.temp_min;
            document.getElementById("tempMax").value = thresholds.temp_max;
            document.getElementById("humidityMin").value = thresholds.humidity_min;
            document.getElementById("humidityMax").value = thresholds.humidity_max;
            document.getElementById("eco2Min").value = thresholds.eco2_min;
            document.getElementById("eco2Max").value = thresholds.eco2_max;
        }

        // Show success message
        function showSuccessMessage() {
            const message = document.getElementById("successMessage");
            message.style.display = "block";

            setTimeout(() => {
                message.style.display = "none";
            }, 3000);
        }

        // Show alerts
        function showAlerts(alerts) {
            const container = document.getElementById("alertsContainer");
            container.innerHTML = "";

            alerts.forEach((alert) => {
                const alertEl = document.createElement("div");
                alertEl.className = `alert alert-${alert.severity}`;
                alertEl.innerHTML = `
                    <span class="icon">${alert.severity === "danger" ? "🚨" : "⚠️"}</span>
                    ${alert.message}
                `;
                container.appendChild(alertEl);
            });
        }
    </script>
</body>
</html>
"""


# Flask Routes
@app.route("/")
def dashboard():
    """Main dashboard route"""
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/current-data")
def api_current_data():
    """API endpoint for current sensor data"""
    return jsonify(
        {
            "tvoc": current_data["tvoc"],
            "temperature": current_data["temperature"],
            "humidity": current_data["humidity"],
            "eco2": current_data["eco2"],
            "timestamp": current_data["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
            "thresholds": thresholds,
        }
    )


@app.route("/api/history")
def api_history():
    """API endpoint for historical data"""
    hours = request.args.get("hours", 24, type=int)
    data = db.get_recent_data(hours)
    return jsonify(data)


@app.route("/api/thresholds", methods=["GET", "POST"])
def api_thresholds():
    """API endpoint for threshold management"""
    if request.method == "POST":
        try:
            new_thresholds = request.get_json()
            # Validate data
            required_keys = [
                "tvoc_max",
                "temp_min",
                "temp_max",
                "humidity_min",
                "humidity_max",
                "eco2_min",
                "eco2_max",
            ]

            for key in required_keys:
                if key not in new_thresholds:
                    return jsonify({"error": f"Missing field {key}"}), 400

            # Convert to float
            for key in required_keys:
                thresholds[key] = float(new_thresholds[key])

            # Validate: min should be less than or equal to max
            if thresholds["temp_min"] > thresholds["temp_max"]:
                return (
                    jsonify(
                        {
                            "error": "Minimum temperature must be less than or equal to maximum temperature!"
                        }
                    ),
                    400,
                )

            if thresholds["humidity_min"] > thresholds["humidity_max"]:
                return (
                    jsonify(
                        {
                            "error": "Minimum humidity must be less than or equal to maximum humidity!"
                        }
                    ),
                    400,
                )

            if thresholds["eco2_min"] > thresholds["eco2_max"]:
                return (
                    jsonify(
                        {
                            "error": "Minimum eCO2 must be less than or equal to maximum eCO2!"
                        }
                    ),
                    400,
                )

            # Save to database
            db.update_thresholds(thresholds)

            # Send update notification via WebSocket
            socketio.emit("thresholds_updated", thresholds)

            logger.info(f"Thresholds updated successfully: {thresholds}")

            return jsonify({"success": True, "thresholds": thresholds})

        except Exception as e:
            logger.error(f"Error updating thresholds: {e}")
            return jsonify({"error": str(e)}), 500

    return jsonify(thresholds)


@app.route("/api/test-alert")
def test_alert():
    """API for testing alert system"""
    message = "🧪 TEST ALERT - System is working normally!"
    send_telegram_alert(message)
    return jsonify({"message": "Test alert sent"})


# SocketIO Events
@socketio.on("connect")
def on_socketio_connect():
    """Handle SocketIO client connection"""
    logger.info(f"SocketIO client connected: {request.sid}")

    # Send current data to newly connected client
    emit(
        "sensor_data",
        {
            "tvoc": current_data["tvoc"],
            "temperature": current_data["temperature"],
            "humidity": current_data["humidity"],
            "eco2": current_data["eco2"],
            "timestamp": current_data["timestamp"].strftime("%H:%M:%S"),
            "alerts": [],
        },
    )


@socketio.on("disconnect")
def on_socketio_disconnect():
    """Handle SocketIO client disconnection"""
    logger.info(f"SocketIO client disconnected: {request.sid}")


if __name__ == "__main__":
    # Run MQTT in separate thread
    mqtt_thread = threading.Thread(target=start_mqtt)
    mqtt_thread.daemon = True
    mqtt_thread.start()

    logger.info("🚀 Starting TVOC Monitoring Server...")
    logger.info("📊 Dashboard: http://localhost:5000")
    logger.info("📡 MQTT Topic: " + MQTT_TOPIC)

    # Run Flask with SocketIO
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
