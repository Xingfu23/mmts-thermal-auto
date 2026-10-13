import time
import psycopg2
import paho.mqtt.publish as publish
import yaml
import os
import sys
import argparse
from datetime import datetime
import subprocess
import requests
import threading

def arguments():
    def safe_path(value):
        import re
        # Allow only ASCII letters, digits, underscores, dots, slashes and hyphens.
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
            raise argparse.ArgumentTypeError(
                "Path may contain only letters, digits, '_', '.', '/', and '-'. Note the bash variables are not allowed."
            )
        return value

    parser = argparse.ArgumentParser(description="Multi-Module Test System (MMTS) automated thermal cycling test")
    parser.add_argument('-m', '--module', type=str, required=False, help="Input module number")
    parser.add_argument('-p', '--mmts_gui_path', type=safe_path, default='/home/ntucms/.local/MultimoduleTeststandUI/', help='MMTS GUI path.')
    args = parser.parse_args()
    return args

def load_config(config_path:str)->None:
    if not os.path.exists(config_path):
        PrintCls.print(f"Error, there is no configuration file: '{config_path}'")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as exc:
            PrintCls.print(f"Error: {exc}")
            sys.exit(1)

def background_logger(stop_event: threading.Event, db_config_telemetry: dict, db_config_hgcdb: dict, batch_id: str):
    """
    Background thread: Every 60s, fetch latest telemetry snapshot and push to hgcdb.
    """
    print(f"\n[LOGGER] Background logging thread started. Pushing data to hgcdb every 60s.")
    

    # sensor_id to log_location
    device_loc_map = {
        "RTD-01": "1", "RTD-02": "2", "RTD-03": "3", "RTD-04": "4",
        "RTD-05": "5", "RTD-06": "6", "RTD-07": "7", "RTD-08": "8",
        "DMT-01": "9", "DMT-02": "10", "Chiller-01": "11",
        "Chiller-T": "12", "Chiller-PrevT": "13", "System Status": "14",
        "RTD-A01": "15", "RTD-A02": "16"
    }

    # SQL Window Function
    fetch_query = """
        SELECT sensor_id, metric, value, measured_at
        FROM (
            SELECT sensor_id, metric, value, measured_at,
                   ROW_NUMBER() OVER(PARTITION BY sensor_id ORDER BY measured_at DESC) as rn
            FROM measurement
        ) tmp
        WHERE rn = 1;
    """

    insert_query = """
        INSERT INTO mmts_sensors_logging 
        (log_timestamp, timestamp_utc, log_location, device_name, value, metric)
        VALUES (%s, %s, %s, %s, %s, %s);
    """

    while not stop_event.is_set():
        try:
            # 1. get snapshot from Telemetry DB
            conn_tel = psycopg2.connect(**db_config_telemetry)
            cur_tel = conn_tel.cursor()
            cur_tel.execute(fetch_query)
            records = cur_tel.fetchall()
            cur_tel.close()
            conn_tel.close()

            if records:
                # 2. insert snapshot to HGCal DB
                conn_hgc = psycopg2.connect(**db_config_hgcdb)
                cur_hgc = conn_hgc.cursor()
                
                for row in records:
                    sensor_id, metric, value, measured_at = row
                    log_location = device_loc_map.get(sensor_id, None)
                    
                    try:
                        numeric_val = float(value)
                    except (TypeError, ValueError):
                        numeric_val = 0.0

                    log_timestamp = datetime.now()
                    cur_hgc.execute(insert_query, (
                        log_timestamp,
                        log_location,
                        sensor_id,
                        numeric_val,
                        metric
                    ))
                
                conn_hgc.commit()
                cur_hgc.close()
                conn_hgc.close()

        except Exception as e:
            print(f"\n[LOGGER_WARNING] Failed to push data to hgcdb: {e}")

        stop_event.wait(60)

    print("\n[LOGGER] Thermal cycle finished. Background logging thread stopped.")

def get_system_status(db_config:dict):
    '''
    Fetch the latest status code from the database
    '''
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        query = """
            SELECT value 
            FROM measurement 
            WHERE sensor_id = 'System Status' 
            ORDER BY measured_at DESC 
            LIMIT 1;
        """
        cur.execute(query)
        result = cur.fetchone()
        cur.close()
        conn.close()
        if result:
                return int(result[0])
    except Exception as e:
        PrintCls.print(f"[ERROR] Failed to connect to the database: {e}")
    return None

def wait_for_status(target_code, db_config, check_interval=1):
    PrintCls.print(f"[INFO] Wait until state reaches [{target_code}] (checked every {check_interval}s)")
    while True:
        current_status = get_system_status(db_config)
        
        if current_status == target_code:
            PrintCls.print(f"\n[INFO] Confirmed system entered state [{target_code}]!")
            break
        elif current_status is not None:
            # \r allows in-place line updates without flooding the console
            print(f"[INFO] Current status code: {current_status}, monitoring...", end="\r", flush=True)
            
        time.sleep(check_interval)

def get_current_temperature(db_config: dict) -> float:
    """
    Fetch the latest average air temperature (avg_air_temp_c) from the avg1m_air_humidity database view
    """
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        query = """
            SELECT avg_air_temp_c 
            FROM avg1m_air_humidity 
            ORDER BY bucket_min DESC 
            LIMIT 1;
        """
        cur.execute(query)
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result and result[0] is not None:
            return float(result[0])
            
    except Exception as e:
        PrintCls.print(f"[ERROR] Failed to fetch temperature from database: {e}")
    
    return None

def get_current_humidity(db_config: dict) -> int:
    """
    Fetch the latest humidity (avg_air_rh_pct) from the database and return as integer.
    """
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        query = """
            SELECT avg_air_rh_pct 
            FROM avg1m_air_humidity 
            ORDER BY bucket_min DESC 
            LIMIT 1;
        """
        cur.execute(query)
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result and result[0] is not None:
            # Convert psycopg2 query result to float and round to nearest integer
            rh_value = float(result[0])
            return int(round(rh_value))
            
    except Exception as e:
        PrintCls.print(f"[ERROR] Failed to fetch humidity from database: {e}")
    
    # Fallback mechanism: return safe default 0 on DB disconnect or query failure to prevent interrupting measurement
    PrintCls.print("[WARNING] Could not get humidity, using default fallback value (0)")
    return 0

def wait_for_temperature(target_temp: float, db_config: dict, check_interval=30):
    """
    Wait loop: Periodically check ambient temperature every 30 seconds until target temperature condition is satisfied, allowable region is plus/minus 2 degree.
    """
    PrintCls.print(f"[INFO] Wait until temperature naturally warms up to {target_temp}°C (checked every {check_interval}s)")
    while True:
        current_temp = get_current_temperature(db_config)
        
        if current_temp is not None:
            if abs(current_temp - target_temp) <= 2.:
                PrintCls.print(f"\n[INFO] Confirmed system temperature reached {current_temp:.2f}°C!")
                break
            else:
                print(f"[INFO] Current temperature: {current_temp:.2f}°C, warming up...", end="\r", flush=True)
                
        time.sleep(check_interval)

class GUI_Fetched_Info:
    def __init__(self, fetchedDICT:dict):
        self.active_modules = {
            key: val for key, val in fetchedDICT.items() 
            if 'moduleID' in key and val != ''
        }
        self.active_inspector = fetchedDICT.get('inspector', "no user")
        self.cycle_count = int( fetchedDICT.get('cycleCOUNT', 5) )
       #self.cycle_count = 5 ### currently it is a constant value

        ### example --stations_and_modules='moduleID1L:320ML53WDNT0893,moduleID1C:320ML53WDNT0841,moduleID1R:,moduleID2L:,moduleID2C:,moduleID2R:,moduleID3L:,moduleID3C:,moduleID3R:,moduleID4L:,moduleID4C:,moduleID4R:,moduleID5L:,moduleID5C:,moduleID5R:,moduleID6L:,moduleID6C:,moduleID6R:,moduleID7L:,moduleID7C:,moduleID7R:,moduleID8L:,moduleID8C:,moduleID8R:'
        self.station_and_moduleID = ','.join( [ f'{key}:{val}' for key,val in fetchedDICT.items() if 'moduleID' in key ] )
    def __str__(self):
        return str({ k:v for k,v in vars(self).items() if "__" not in k })
    def __repr__(self):
        return self.__str__()
        
def fetch_modules_from_gui(port=5001) -> GUI_Fetched_Info:
    """
    Request currently configured module ID from Flask GUI.
    Args:
        port: Target port for the Flask server (pass 5001 if Flask runs with debug=False).
    Returns:
        The module ID string configured by the user.
    """
    PrintCls.print(f'[INFO] Fetch information from MMTS GUI')
    api_url = f"http://127.0.0.1:{port}/api/get_config"
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        gui_config = response.json()

        fetched_info =  GUI_Fetched_Info(gui_config)
        PrintCls.print(f'[INFO] Fetch information from MMTS GUI ENDED')
        
        return fetched_info
    
    except requests.exceptions.RequestException as e:
        PrintCls.print(f"[ERROR] Failed to connect to Flask GUI to retrieve module ID; ensure web server is running on port {port}. ({e})")
        sys.exit(1)

def run_iv_curve_test(batch_id, modules_dict, iteration, target_temp, db_config, max_voltage=500, inspector='no user', mmtsGUIpath='', nCYCLE = 5)->bool:
    """
    Trigger I-V curve scan locally on AlmaLinux and block until complete
    """
    # batch_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    current_humidity = get_current_humidity(db_config)
    module_args = " ".join([f"{k}={v}" for k, v in modules_dict.items()]) # Key step: Convert module dictionary into command-line arguments for make

    PrintCls.print(f"\n[IV_TEST] =========================================")
    PrintCls.print(f"[IV_TEST] Preparing to start measurement: {iteration} | Target Temp: {target_temp}°C | Max Voltage: {max_voltage}V")
    PrintCls.print(f"[IV_TEST] Testing modules: {module_args}")

    bash_cmd = f"""
    echo "[Goto MMTS GUI Path] '{mmtsGUIpath}'"; \
    cd "{mmtsGUIpath}" && \
    source init_bash_vars.sh && \
    source .venv/bin/activate && \
    make -f makefile_task3 run {module_args} iteration='{iteration}' currentTEMPERATURE='{target_temp}' currentHUMIDITY='{current_humidity}' batch='{batch_id}' maxVOLTAGE='{max_voltage}' inspector='{inspector}' cycleCOUNT='{nCYCLE}'
    """

    PrintCls.print("[IV_TEST] Running underlying measurement routine, please wait...")

    # Execute bash command and stream output directly to terminal
    try:
        process = subprocess.run(
            bash_cmd, 
            shell=True, 
            executable='/bin/bash', 
            check=True
        )
        PrintCls.print(f"[IV_TEST] {iteration} measurement completed!")
        PrintCls.print(f"[IV_TEST] =========================================\n")
        return True
    
    except subprocess.CalledProcessError as e:
        PrintCls.print(f"[IV_TEST] [ERROR] Measurement execution failed (exit code: {e.returncode})")
        PrintCls.print(f"[IV_TEST] =========================================\n")
        return False

def emergency_abort(mqtt_broker, port, command_topic, mmtsGUIpath='', stop_event=None):
    '''
    Emergency abort procedure: Shut down chiller and safely ramp down power supply
    '''
    if stop_event:
        stop_event.set()

    PrintCls.print("\n[EMERGENCY] Keyboard interrupt detected (Ctrl+C)! Initiating Emergency Stop (E-Stop) procedure...")
    
    # 1. Shut down chiller (send set_S)
    PrintCls.print("[EMERGENCY] 1. Sending command to shut down chiller...")
    try:
        publish.single(command_topic, payload="set_S", hostname=mqtt_broker, port=port)
        PrintCls.print("[EMERGENCY] -> Chiller received stop command.")
    except Exception as e:
        PrintCls.print(f"[EMERGENCY] -> Failed to send chiller abort command: {e}")
        PrintCls.print(f"Please stop chiller manually")
    
    # 2. Trigger make stop to safely power down instrumentation
    PrintCls.print("[EMERGENCY] 2. Safely shutting down power supply and measurement systems...")
    stop_cmd = f"""
    echo "[Goto MMTS GUI Path] '{mmtsGUIpath}'"; \
    cd "{mmtsGUIpath}" && \
    source init_bash_vars.sh && \
    source .venv/bin/activate && \
    make -f makefile_task3 stop
    """
    try:
        subprocess.run(stop_cmd, shell=True, executable='/bin/bash', check=False)
        # Adopt MMTS GUI pattern to forcefully kill all lingering background make processes
        os.system('pkill make 2>/dev/null')
        PrintCls.print("[EMERGENCY] -> Power supply safely aborted.")
    except Exception as e:
        PrintCls.print(f"[EMERGENCY] -> Failed to abort power supply: {e}")

    PrintCls.print("[EMERGENCY] Emergency abort procedure completed! System returned to standby.")

def push_message_to_HGCDB(mmtsBASE, mesg, batch, iteration, cycleCOUNT, stationsANDmodules):
    ''' used to put a log to HGCDB mmts_batch_logging '''
    cmd = f''' {mmtsBASE}/.venv/bin/python3 {mmtsBASE}/scripts/mmts_batch_logging.create_an_entry.py -c {mmtsBASE}/data/mmts_configurations.yaml --description='{mesg.strip()}' --batch='{batch}' --iteration='{iteration}' --cycle_count='{cycleCOUNT}' --stations_and_modules='{stationsANDmodules}' '''
    os.system(cmd)

class PrintCls:
    mmts_base = None
    batch_name = ''
    iteration = ''
    cycle_count = 0
    stations_and_modules = 'moduleID1L:,moduleID1C:,moduleID1R:,moduleID2L:,moduleID2C:,moduleID2R:,moduleID3L:,moduleID3C:,moduleID3R:,moduleID4L:,moduleID4C:,moduleID4R:,moduleID5L:,moduleID5C:,moduleID5R:,moduleID6L:,moduleID6C:,moduleID6R:,moduleID7L:,moduleID7C:,moduleID7R:,moduleID8L:,moduleID8C:,moduleID8R:'

    SHOW_DEBUG_INFO = True

    @classmethod
    def print(cls, mesg):
        ''' replacing the print() function. Once the cls instance was setup, also put the message into HGCDB '''
        print(mesg)
        
        if cls.mmts_base is not None:
            if '[DEBUG]' in mesg and cls.SHOW_DEBUG_INFO == False: return
            push_message_to_HGCDB(
                mmtsBASE = cls.mmts_base,
                mesg = mesg,
                batch = cls.batch_name,
                iteration = cls.iteration,
                cycleCOUNT = cls.cycle_count,
                stationsANDmodules = cls.stations_and_modules
            )





def main(config_path)->None:

    args = arguments()
    config = load_config(config_path)
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    host = config['database']['DB_HOST']
    database = config['database']['DB_NAME']
    user = config['database']['DB_USER']
    password = config['database']['DB_PASSWORD']

    DB_CONFIG_TEL = {
        "host": config['database']['DB_HOST'],
        "database": config['database']['DB_NAME'],
        "user": config['database']['DB_USER'],
        "password": config['database']['DB_PASSWORD']
    }
    
    DB_CONFIG_HGC = {
        "host": config['hgcdb']['DB_HOST'],
        "port": config['hgcdb'].get('DB_PORT', 5432),
        "database": config['hgcdb']['DB_NAME'],
        "user": config['hgcdb']['DB_USER'],
        "password": config['hgcdb']['DB_PASSWORD']
    }

    MQTT_BROKER_IP = config['mqtt']['MQTT_BROKER']
    COMMAND_TOPIC = config['mqtt']['COMMAND_TOPIC']
    PORT = config['mqtt']['MQTT_PORT']

    logging_stop_event = threading.Event()

    # =============== Start scenario ===============
    PrintCls.mmts_base = args.mmts_gui_path
    PrintCls.batch_name = batch_id
    try:
        PrintCls.print("[INFO] Multi-Module Test System closed-loop test started")

        # ---------------------------------------------------------
        # Step 0: Fetch module configuration from GUI
        # ---------------------------------------------------------
        PrintCls.print("[INFO] Step0: Requesting current module ID configuration from Flask GUI...")

        fetched_info = fetch_modules_from_gui(port=5001)

        PrintCls.print(f"[DEBUG] accessed information {fetched_info}")
        active_modules = fetched_info.active_modules
        active_inspector = fetched_info.active_inspector
        num_cycles = fetched_info.cycle_count
        set_cycles = fetched_info.cycle_count - 1 ## it should be N-1 for this code
        PrintCls.print(f'[DEBUG] num_cycles is "{num_cycles}" and set_cycle "{set_cycles}" to 2nd IV code')
        if set_cycles < 1:
            PrintCls.print("[InvalidCycleCount] cycle count '{num_cycles}' is rejected, which is expected in range [2,1000].")
            return

        PrintCls.stations_and_modules = fetched_info.station_and_moduleID
        
        set_ncycle_cmd = f'nCYC_{set_cycles}' if set_cycles else 'nCYC_5' ### nCYC_20 for 20 runs. Default is nCYC_5
        PrintCls.print(f'[SetNCycle] cycle count "{num_cycles}" grabed. generating command "{set_ncycle_cmd}"')
        PrintCls.print(f"\n[INFO] Step 0: Sending command {set_ncycle_cmd} (set number of cycles)")
        publish.single(COMMAND_TOPIC, payload=set_ncycle_cmd, hostname=MQTT_BROKER_IP, port=PORT)


        if not active_modules:
            PrintCls.print("[ERROR] No modules configured in Web GUI. Please configure modules on the webpage and click Configure first!")
            return

        PrintCls.print(f"[INFO] Successfully retrieved {len(active_modules)} module(s). Preparing to start automated test.")

        logger_thread = threading.Thread(
            target=background_logger, 
            args=(logging_stop_event, DB_CONFIG_TEL, DB_CONFIG_HGC, batch_id),
            daemon=True
        )
        logger_thread.start()

        DB_CONFIG = DB_CONFIG_TEL

        current_status = get_system_status(DB_CONFIG)
        if current_status == 0: ## this is system Alert
            PrintCls.print(f'[ERROR] System Alert form hardward side. Ex. Door is not locked.   ... abort software.')
            return

        # ---------------------------------------------------------
        # Step 1: Iteration 1, room temperature, high humidity
        # ---------------------------------------------------------
        PrintCls.iteration = "iteration_1"
        PrintCls.print('[INFO] Step 1: (Iteration 1) Starting room temperature (20°C) I-V Curve measurement')
        success = run_iv_curve_test(
            batch_id=batch_id,
            modules_dict=active_modules,
            iteration="iteration_1",
            db_config=DB_CONFIG,
            target_temp=20,
            inspector = active_inspector,
            mmtsGUIpath = args.mmts_gui_path,
            nCYCLE = num_cycles,
        )
        if not success:
            PrintCls.print("[ERROR] Iteration 1 measurement failed, terminating workflow!")
            return
       #return ### asdf

        
        # ---------------------------------------------------------
        # Step 2: Cooling down to -40°C
        # ---------------------------------------------------------
        PrintCls.print("\n[INFO] Step 2: Sending command set_A (start cooling)")
        publish.single(COMMAND_TOPIC, payload='set_A', hostname=MQTT_BROKER_IP, port=PORT)
       
        wait_for_status(4, DB_CONFIG) # Wait for state code becoming 4 (Countdown Cooling)
        PrintCls.print("[INFO] System reached -40°C target state; waiting 600s to ensure thermal equilibrium...")
        time.sleep(600)

        # ---------------------------------------------------------
        # Step 3: Iteration 2, low-temperature (-40°C) I-V Curve
        # ---------------------------------------------------------
        PrintCls.iteration = "iteration_2"
        PrintCls.print("[INFO] Step 3: Starting low-temperature (-40°C) I-V Curve measurement (Iteration 2)")
        success = run_iv_curve_test(
            batch_id=batch_id,
            modules_dict=active_modules,
            iteration="iteration_2",
            db_config=DB_CONFIG,
            target_temp=-40,
            inspector = active_inspector,
            mmtsGUIpath = args.mmts_gui_path,
            nCYCLE = num_cycles,
        )

        if not success:
            PrintCls.print("[ERROR] Step 3 measurement failed, executing emergency abort sequence!")
            publish.single(COMMAND_TOPIC, payload="set_S", hostname=MQTT_BROKER_IP, port=PORT)
            return
        
        # ---------------------------------------------------------
        # Step 4: Stop cooling, start main thermal cycling procedure
        # ---------------------------------------------------------
        PrintCls.print("\n[INFO] Step 4: Measurement success, sending stop command before starting thermal cycle")
        publish.single(COMMAND_TOPIC, payload="set_S", hostname=MQTT_BROKER_IP, port=PORT)
        time.sleep(10)
        PrintCls.cycle_count += 1
        PrintCls.print("[INFO] Initiating thermal cycling procedure (set_B)")
        publish.single(COMMAND_TOPIC, payload='set_B', hostname=MQTT_BROKER_IP, port=PORT)
        time.sleep(300)

        # ---------------------------------------------------------
        # Step 5: Wait for thermal cycle to end, cool down to -40°C again
        # ---------------------------------------------------------
        PrintCls.print("\n[INFO] Step 5: Waiting for thermal cycle to complete and return to Standby...")
        wait_for_status(1, DB_CONFIG, 10)
        PrintCls.cycle_count = num_cycles-1
        
        PrintCls.print("[INFO] Thermal cycle completed. Initiating cool down to (-40°C) again (set_A)")
        publish.single(COMMAND_TOPIC, payload='set_A', hostname=MQTT_BROKER_IP, port=PORT)

        # ---------------------------------------------------------
        # Step 6: Iteration 3, post-cycle low-temperature (-40°C, 850V)
        # ---------------------------------------------------------
        wait_for_status(4, DB_CONFIG)
        PrintCls.print("[INFO] System reached -40°C target state; waiting 600s to ensure thermal equilibrium...")
        time.sleep(600)
        
        PrintCls.iteration = "iteration_3"
        PrintCls.print('\n[INFO] Step 6: (Iteration 3) Starting post-cycle low-temperature (-40°C) I-V Curve measurement')
        success = run_iv_curve_test(
            batch_id=batch_id,
            modules_dict=active_modules,
            iteration="iteration_3",
            target_temp=-40,
            db_config=DB_CONFIG,
            max_voltage=850,
            inspector = active_inspector,
            mmtsGUIpath = args.mmts_gui_path,
            nCYCLE = num_cycles,
        )
        if not success:
            PrintCls.print("[ERROR] Step 6 measurement failed, executing emergency abort sequence!")
            publish.single(COMMAND_TOPIC, payload="set_S", hostname=MQTT_BROKER_IP, port=PORT)
            return

        # ---------------------------------------------------------
        # Step 7: Returning to standby (Natural warming begins)
        # ---------------------------------------------------------
        PrintCls.print("\n[INFO] Step 7: Sending command set_S to stop chiller and return to Standby")
        publish.single(COMMAND_TOPIC, payload="set_S", hostname=MQTT_BROKER_IP, port=PORT)

        # ---------------------------------------------------------
        # Step 8: Wait for natural warming to 20°C, Iteration 4 (20°C, 850V)
        # ---------------------------------------------------------
        PrintCls.print("\n[INFO] Step 8: Waiting for system temperature to return to 20°C for final measurement...")
        wait_for_temperature(20.0, DB_CONFIG)
        PrintCls.cycle_count = num_cycles
        
        PrintCls.print("[INFO] System reached 20°C target state; waiting 600s to ensure thermal equilibrium...")
        time.sleep(600)

        PrintCls.iteration = "iteration_4"
        PrintCls.print('\n[INFO] Step 8: (Iteration 4) Starting final room temperature (20°C) I-V Curve measurement')
        success = run_iv_curve_test(
            batch_id=batch_id,
            modules_dict=active_modules,
            iteration="iteration_4",
            target_temp=20,
            db_config=DB_CONFIG,
            max_voltage=850,
            inspector = active_inspector,
            mmtsGUIpath = args.mmts_gui_path,
            nCYCLE = num_cycles,
        )

        PrintCls.print("\n[INFO] Test completed successfully; data saved, system safely returned to Standby.")

    except KeyboardInterrupt:
        # Handle user interrupt: execution jumps here when Ctrl+C is pressed
        emergency_abort(MQTT_BROKER_IP, PORT, COMMAND_TOPIC, mmtsGUIpath=args.mmts_gui_path, stop_event=logging_stop_event)
        sys.exit(1)
    
    except Exception as e:
        # Execute fail-safe protection routine upon catching unhandled Python exceptions
        PrintCls.print(f"\n[ERROR] An unexpected error occurred: {e}")
        emergency_abort(MQTT_BROKER_IP, PORT, COMMAND_TOPIC, mmtsGUIpath=args.mmts_gui_path, stop_event=logging_stop_event)
        sys.exit(1)
        
    finally:
        logging_stop_event.set()

if __name__ == '__main__':
    config_path = 'gateway_setting.yml'
    main(config_path)
