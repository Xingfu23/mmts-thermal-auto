import paho.mqtt.client as mqtt
import subprocess
import sys
import re

BROKER_IP = "mosquitto"
COMMAND_TOPIC = "plc/s7-1200/temperature/command"

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Listener stand by, waiting for instruction...")
        client.subscribe(COMMAND_TOPIC)

def on_message(client, userdata, msg):
    command = msg.payload.decode('utf-8')
    print(f"\nCommand received.")
    print(f"Command: {command}")

    try:
        if command == "set_A":
            run_command = [sys.executable, 'control_hmi.py', '-c', 'Set_cool_down.yml', '-f']
            print(f"Cooling down, command:{run_command}")
            subprocess.run(run_command, check=True)
            print("Command sent out sucessfully.")
            
        elif command == "set_S":
            run_command = [sys.executable, 'control_hmi.py', '-s']
            print("Stop, command:{}")
            subprocess.run(run_command, check=True)
            print("Chiller Stop.")
        
        elif command == "set_B":
            run_command = [sys.executable, 'control_hmi.py', '-c', 'Set_multi_cycle.yml', '-f']
            print(f"Thermal cycling, command:{run_command}")
            subprocess.run(run_command, check=True)
            print("Command sent out sucessfully.")
            
        elif re.match(r"^nCYC_(\d+)$", command):
            match = re.match(r"^nCYC_(\d+)$", command)
            cycles = int(match.group(1))

            if cycles <= 0 or cycles > 1000:
                print(f'[OutOfRange] new cycle "{cycles}" is out of range 0~1000. Use default 5 cycles.')
                cycles = 5

            config_filename = "Set_multi_cycle.yml"
            print(f"--> Dynamic cycle request: {cycles} cycles")

            gen_command = [
                sys.executable, 'config_generater.py',
                '-c', str(cycles),
                '-s', 'Set_5_cycle_temp.yml',
                '-o', config_filename
            ]
            print(f"Generating config: {gen_command}")
            subprocess.run(gen_command, check=True)
            print(f"Configuration file '{config_filename}' generated successfully (Ready, not executed).")
        else:
            print("Unkown command, no action applied")
    
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {e}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER_IP, 1883, 60)
client.loop_forever()