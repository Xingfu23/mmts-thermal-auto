import argparse
import os
import sys
import yaml


def load_source_config(source_path: str) -> dict:
    """
    Load and parse the base YAML configuration file.
    """
    if not os.path.exists(source_path):
        print(f"Error: Source configuration file '{source_path}' not found.")
        sys.exit(1)
    with open(source_path, "r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            print(f"Error reading YAML file '{source_path}': {exc}")
            sys.exit(1)


def build_config_content(
    cycles: int,
    plc_ip="[PLC IP]",
    plc_rack=0,
    plc_slot=1,
    plc_db=15,
    temp_high=20.0,
    temp_low=-40.0,
    idle_warm_min=10,
    idle_cold_min=60,
    temp_high_limit=30.0,
    temp_low_limit=-50.0,
    dry_run=True,
    db_host="[database IP]",
    db_port="[database port]",
    db_user="[database user]",
    db_name="[database name]",
    db_password="[database password]",
    mqtt_broker="[broker IP]",
    mqtt_port="[broker port]",
    mqtt_topic="plc/s7-1200/temperature",
) -> str:
    """
    Build the YAML configuration string dynamically, preserving structure and comments.
    """
    return f"""# config.yaml
plc:
  ip: {plc_ip}
  rack: {plc_rack}
  slot: {plc_slot}
  db_number: {plc_db}

experiment:
  # configuration
  temp_high: {temp_high}
  temp_low: {temp_low}
  cycles: {cycles}
  idle_warm_min: {idle_warm_min}
  idle_cold_min: {idle_cold_min}
  # safty
  temp_high_limit: {temp_high_limit}
  temp_low_limit: {temp_low_limit}

execution:
  dry_run: {'true' if dry_run else 'false'}      

database:
  DB_HOST: {db_host}
  DB_PORT: {db_port}
  DB_USER: {db_user}
  DB_NAME: {db_name}
  DB_PASSWORD: {db_password}

mqtt:
  MQTT_BROKER: {mqtt_broker}
  MQTT_PORT: {mqtt_port}
  MQTT_TOPIC: {mqtt_topic}
"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate a new thermal cycle YAML configuration with custom cycles."
    )
    # Positional argument: pure integer for cycle count
    parser.add_argument(
        "-c",
        "--cycles",
        type=int,
        help="Number of cycles to run (positive integer, e.g., 5)",
    )
    # Optional input source file to inherit settings from
    parser.add_argument(
        "-s",
        "--source",
        default=None,
        help="Path to an existing YAML file to inherit PLC, Database, and MQTT settings from (e.g., HMI_Control.yml)",
    )
    # Output file path
    parser.add_argument(
        "-o",
        "--output",
        default="HMI_Control_new.yml",
        help="Target output YAML filename (default: HMI_Control_new.yml)",
    )
    # Optional overrides for temperature targets
    parser.add_argument(
        "--temp-high",
        type=float,
        default=None,
        help="Override high temperature target (e.g., 20.0)",
    )
    parser.add_argument(
        "--temp-low",
        type=float,
        default=None,
        help="Override low temperature target (e.g., -40.0)",
    )

    args = parser.parse_args()

    # Validate cycles
    if args.cycles <= 0:
        print(f"Error: cycle count must be greater than 0 (received: {args.cycles})")
        sys.exit(1)

    # Defaults
    plc_ip, plc_rack, plc_slot, plc_db = "[PLC IP]", 0, 1, 15
    temp_high, temp_low = 20.0, -40.0
    idle_warm_min, idle_cold_min = 10, 60
    temp_high_limit, temp_low_limit = 30.0, -50.0
    dry_run = True
    db_host, db_port, db_user = "[database IP]", "[database port]", "[database user]"
    db_name, db_password = "[database name]", "[database password]"
    mqtt_broker, mqtt_port, mqtt_topic = "[broker IP]", "[broker port]", "plc/s7-1200/temperature"

    # Load existing settings if a source file is provided
    if args.source:
        src = load_source_config(args.source)
        print(f"Reading base parameters from source file: '{args.source}'")

        plc_sec = src.get("plc", {})
        plc_ip = plc_sec.get("ip", plc_ip)
        plc_rack = plc_sec.get("rack", plc_rack)
        plc_slot = plc_sec.get("slot", plc_slot)
        plc_db = plc_sec.get("db_number", plc_db)

        exp_sec = src.get("experiment", {})
        temp_high = exp_sec.get("temp_high", temp_high)
        temp_low = exp_sec.get("temp_low", temp_low)
        idle_warm_min = exp_sec.get("idle_warm_min", idle_warm_min)
        idle_cold_min = exp_sec.get("idle_cold_min", idle_cold_min)
        temp_high_limit = exp_sec.get("temp_high_limit", temp_high_limit)
        temp_low_limit = exp_sec.get("temp_low_limit", temp_low_limit)

        exec_sec = src.get("execution", {})
        dry_run = exec_sec.get("dry_run", dry_run)

        db_sec = src.get("database", {})
        db_host = db_sec.get("DB_HOST", db_host)
        db_port = db_sec.get("DB_PORT", db_port)
        db_user = db_sec.get("DB_USER", db_user)
        db_name = db_sec.get("DB_NAME", db_name)
        db_password = db_sec.get("DB_PASSWORD", db_password)

        mqtt_sec = src.get("mqtt", {})
        mqtt_broker = mqtt_sec.get("MQTT_BROKER", mqtt_broker)
        mqtt_port = mqtt_sec.get("MQTT_PORT", mqtt_port)
        mqtt_topic = mqtt_sec.get("MQTT_TOPIC", mqtt_topic)

    # Command-line temperature overrides take precedence
    if args.temp_high is not None:
        temp_high = args.temp_high
    if args.temp_low is not None:
        temp_low = args.temp_low

    # Generate content and write to target file
    content = build_config_content(
        cycles=args.cycles,
        plc_ip=plc_ip,
        plc_rack=plc_rack,
        plc_slot=plc_slot,
        plc_db=plc_db,
        temp_high=temp_high,
        temp_low=temp_low,
        idle_warm_min=idle_warm_min,
        idle_cold_min=idle_cold_min,
        temp_high_limit=temp_high_limit,
        temp_low_limit=temp_low_limit,
        dry_run=dry_run,
        db_host=db_host,
        db_port=db_port,
        db_user=db_user,
        db_name=db_name,
        db_password=db_password,
        mqtt_broker=mqtt_broker,
        mqtt_port=mqtt_port,
        mqtt_topic=mqtt_topic,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Successfully generated '{args.output}' with cycles set to {args.cycles}.")


if __name__ == "__main__":
    main()