import os
import paho.mqtt.publish as publish
import time

BROKER_IP = os.getenv("MQTT_BROKER", "127.0.0.1")  # e.g., "192.168.x.x"

COMMAND_TOPIC = "plc/s7-1200/temperature/command"

print("【測試情境開始】")

# 1. 發送降溫指令
print("發送指令: set_A (開始降溫)")
publish.single(COMMAND_TOPIC, payload="set_A", hostname=BROKER_IP, port=1883)

# 2. 模擬系統運作中
wait_time = 120
print(f"等待 {wait_time} 秒鐘，觀察系統是否正常開始降溫...")
for i in range(wait_time, 0, -1):
    print(f"剩餘 {i} 秒...", end="\r")
    time.sleep(1)
print("\n")

# 3. 發送中止指令
print("發送指令: set_S (緊急中止)")
publish.single(COMMAND_TOPIC, payload="set_S", hostname=BROKER_IP, port=1883)

print("【測試情境結束】")