import numpy as np
import snap7
from snap7.util import set_int, set_real, set_bool, get_bool
from snap7.type import Areas
import time
import argparse
import yaml
import os
import sys

# Loading yaml configuration file
def load_config(config_path:str)->None:
    if not os.path.exists(config_path):
        print(f"Error, there is no configuration file: '{config_path}'")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as exc:
            print(f"Error: {exc}")
            sys.exit(1)

def create_client(plc_config):
    client = snap7.client.Client()
    try:
        client.connect(plc_config['ip'], plc_config['rack'], plc_config['slot'])
        return client
    except Exception as e:
        print(f"PLC connection failed: {e}")
        return None

def read_sensor_real(client, db_number, offset):
    '''
    Accessing the real number value stored in db area.
    '''
    data = client.db_read(db_number, offset, 4) # real occupied 4 bytes
    return snap7.util.get_real(data, 0)

def read_sensor_bool(client, db_number, byte_offset, bit_index):
    '''
    Accessing the boolean value stored in db area.
    '''
    data = client.db_read(db_number, byte_offset, 1)
    return snap7.util.get_bool(data, 0, bit_index)

def read_m_bool(client, byte_offset, bit_index):
    '''
    Accessing the boolean value stored in memory.
    '''
    data = client.read_area(Areas.MK, 0, byte_offset, 1)
    return get_bool(data, 0, bit_index)

def write_temp_setpoint(client, db_number, offset, value):
    data = bytearray(4) 
    set_real(data, 0, value)
    client.db_write(db_number, offset, data)

def write_int_value(client, db_number, offset, value):
    data = bytearray(2)
    set_int(data, 0, value)
    client.db_write(db_number, offset, data)

def system_status(client)->list:
    '''
    Reading the current operational status of the chiller. 
    The function will send out an integer to represent the operation status:
    0. The door is open. Please check the system.
    1. Standby 
    2. Countdown - Warming Stage 
    3. Warming Up 
    4. Countdown - Cooling Stage 
    5. Cooling Down.
    '''

    print('Reading current operation status of chiller')
    status_code = 0
    status_dict = {
        0: 'The door is open. Please check the system.',
        1: 'Statndby',
        2: 'Countdown-Warming Stage ',
        3: 'Warming up',
        4: 'Countdown-Cooling Stage ',
        5: 'Cooling down'
    }
    result = [0, 'Door is open, please check the system']

    idle_running = read_sensor_bool(client, 15, 540, 0)
    is_go_cold = read_m_bool(client, byte_offset=100, bit_index=4)
    is_go_warm = read_m_bool(client, byte_offset=100, bit_index=3)
    is_door_lock = read_m_bool(client, byte_offset=60, bit_index=0)

    if not is_door_lock:
        result = [status_code, status_dict[status_code]]
        return result

    if idle_running:
        if is_go_warm:
            status_code = 2
        elif is_go_cold:
            status_code = 4
        else:
            status_code = 1
    else:
        if is_go_warm and not is_go_cold:
            status_code = 3
        elif is_go_cold and not is_go_warm:
            status_code = 5
        else:
            status_code = 1
    
    result = [status_code, status_dict[status_code]]
    return result

def avg_dewpoint(client)->float:
    dewpoint1 = read_sensor_real(client, 15, 314)
    dewpoint2 = read_sensor_real(client, 15, 356)
    avg_dewpoint = np.mean([dewpoint1, dewpoint2])
    return avg_dewpoint