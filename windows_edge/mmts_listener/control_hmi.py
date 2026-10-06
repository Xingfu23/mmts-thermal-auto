import snap7
from snap7.util import set_int, set_real, set_bool, get_bool
import time
import argparse
import yaml
import os
import sys

from plc_io import load_config, create_client, read_sensor_real, read_sensor_bool, write_temp_setpoint, write_int_value, system_status, avg_dewpoint

def parse_args():
    parser = argparse.ArgumentParser(description='PLC Thermal Cycle Controller')
    parser.add_argument('-c', '--config', default='HMI_Control.yml', help='Path to the YAML config file')
    parser.add_argument('-f', '--force-run', action='store_true', help='Override yaml dry_run setting to execute immediately')
    parser.add_argument('-s', '--stop', action='store_true', help='Send STOP signal to the PLC immediately')
    return parser.parse_args()

def press_hmi_button(client, db_number, byte_offset, bit_index, button_name):
    # 1. Reading current status
    data = client.db_read(db_number, byte_offset, 1)

    # 2. Press the button 
    set_bool(data, 0, bit_index, True)
    client.db_write(db_number, byte_offset, data)
    print(f"  -> Press {button_name} button")

    time.sleep(0.3) # Simulate pressing button

    # 3. Release the button
    data = client.db_read(db_number, byte_offset, 1)
    current_bit_state = get_bool(data, 0, bit_index)
    if current_bit_state:
        set_bool(data, 0, bit_index, False)
        client.db_write(db_number, byte_offset, data)
        print(f"  -> Release {button_name} button")
    else:
        pass 

def smart_start(client, db_number):
    print("\n[System Check & Start Sequence]")
    
    # 0. Actulalize the setting value (by configuration file)
    press_hmi_button(client, db_number, 557, 5, "ACT_DATA (Actualize Data)")
    time.sleep(0.5)

    # 1. Reset the Alarm
    press_hmi_button(client, db_number, 556, 5, "ALM_RES")
    time.sleep(0.5)
    
    # 2. Make sure the PLC is in the AUTO mode
    data = client.db_read(db_number, 556, 1)
    if not get_bool(data, 0, 1):
        print("  -> System not in AUTO, setting AUTO mode...")
        press_hmi_button(client, db_number, 556, 1, "AUTO")
        time.sleep(0.5)

    # 3. Sending start signal
    press_hmi_button(client, db_number, 556, 0, "START")
    print("  => Start sequence completed.\n")

def main():
    args = parse_args()
    cfg = load_config(args.config)
    print(f"Loading config file:{args.config}")
    
    plc_cfg = cfg['plc']
    exp_cfg = cfg['experiment']
    db_num = plc_cfg['db_number']

    high_temp_target = exp_cfg['temp_high']
    low_temp_target = exp_cfg['temp_low']
    high_temp_limit = exp_cfg['temp_high_limit']
    low_temp_limit = exp_cfg['temp_low_limit']

    if (high_temp_target > high_temp_limit) or (low_temp_target < low_temp_limit):
        print(f"Error: The target temperature is outside the safety region.")
        return
    if (high_temp_target <= low_temp_target):
        print(f"Error: The lower target temperature is higher than or equal to the high target temperature.")
        return

    is_dry_run = False if args.force_run else cfg['execution']['dry_run']
    
    # Establish the connection
    client = create_client(plc_cfg)
    if not client or not client.get_connected():
        print("PLC connection failed, abort!")
        return
    
    try:
        max_retries = 30

        # Stop Mode
        if args.stop:
            print("Sending STOP signal to PLC...")

            for retry in range(max_retries):
                print(f"=== Sending STOP command, try {retry + 1}/{max_retries}===\n")
                press_hmi_button(client, db_num, 556, 2, "STOP")
                current_target = read_sensor_real(client, db_num, 418)

                time.sleep(0.5) # Giving time for PLC process status code

                status_code, status_msg = system_status(client)

                if status_code == 1:
                    print(f"System stopped successfully. Current Status: {status_msg}")
                    return
                
                print("System did not stop, we will try again later.")
                time.sleep(2.0)
            
            print("Reached retry number limit. System cannot be stopped automatically. Please stop manually.")
            return
        
        # Dry run
        if is_dry_run:
            status_code, status_msg = system_status(client) 
            print('Simulation mode: Check bypassed.')
            print(f"Current Status: {status_msg}, Status Code: {status_code}")
            return
        
        # Execution Mode
        for retry in range(max_retries):
            status_code, status_msg = system_status(client)
            current_dewpoint = avg_dewpoint(client)

            if status_code != 1:
                print(f"Warning: System is not in standby mode (Code: {status_code}). Operation terminated.")
                return
            if low_temp_target < current_dewpoint - 10.0:
                print(f"Warning: The target low temperature ({low_temp_target}℃) is significantly lower than the current average dew point ({current_dewpoint:.2f}℃). Operation terminated.")
                return
            
            print(f"=== Sending command, try {retry + 1}/{max_retries} ===")
            # Writing parameters from the configuration file
            write_temp_setpoint(client, db_num, 468, exp_cfg['temp_low'])
            write_temp_setpoint(client, db_num, 472, exp_cfg['temp_high'])
            write_int_value(client, db_num, 548, exp_cfg['cycles'])
            write_int_value(client, db_num, 536, exp_cfg['idle_cold_min'])
            write_int_value(client, db_num, 538, exp_cfg['idle_warm_min'])

            print("Proceeding thermal cycle...")
            smart_start(client, db_num)
            time.sleep(2.0)

            current_target = read_sensor_real(client, db_num, 418)
            print(f"Current Target Temperature: {current_target}℃ | Expected: {low_temp_target}℃ | Diff: {abs(current_target - low_temp_target):.2f}")

            if abs(current_target - low_temp_target) < 0.01:
                print("New setting is loaded successfully.")
                return
            
            print("Setting is not loaded in, we will try again later.")
            time.sleep(1.0)
        
        print("Reached maximum retry number, please check the PLC status.")

    except Exception as e:
        print(f"Error Occur: {e}")
    
    finally:
        client.disconnect()
        print('=========================')
        print('Process complete. PLC is now disconnected.')

if __name__ == "__main__":
    main()