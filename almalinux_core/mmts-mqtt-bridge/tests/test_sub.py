import os
import paho.mqtt.client as mqtt

BROKER_IP = os.getenv("MQTT_BROKER", "127.0.0.1")  # e.g., "192.168.x.x"

TOPIC = "plc/s7-1200/temperature" 

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✅ 成功連線至 Windows MQTT Broker!")
        client.subscribe(TOPIC)
        print("📡 已訂閱主題: # (正在監聽所有訊息...)")
    else:
        print(f"❌ 連線失敗，錯誤代碼: {reason_code}")

def on_message(client, userdata, msg):
    print(f"收到資料 [{msg.topic}]: {msg.payload.decode('utf-8')}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

print(f"嘗試連線至 {BROKER_IP}:1883...")
client.connect(BROKER_IP, 1883, 60)

# 讓程式保持執行，持續監聽
client.loop_forever()