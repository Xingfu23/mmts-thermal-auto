import os
import paho.mqtt.publish as publish

def main():
    BROKER_IP = os.getenv("MQTT_BROKER", "127.0.0.1")  # e.g., "192.168.x.x"

    COMMAND_TOPIC = "plc/s7-1200/temperature/command"
    
    TEST_PAYLOAD = "SET_A"
    print(f'Ready to send command: {TEST_PAYLOAD} to the TOPIC: {COMMAND_TOPIC}')

    publish.single(
        topic=COMMAND_TOPIC,
        payload=TEST_PAYLOAD,
        hostname=BROKER_IP,
        port=1883
)

print("Command sent out Successfully")
if __name__ == '__main__':
    main()