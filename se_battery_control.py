import argparse
import logging
from logging.handlers import RotatingFileHandler
import json
from datetime import datetime
import time
import solaredge_modbus
import yaml
from pymodbus import exceptions as pymbEx

LOGGER_LEVEL = logging.INFO  # Logging level DEBUG, INFO, WARNING, ERROR, CRITICAL
LOGGER_NAME = "se_battery_control"
LOG_FILE = LOGGER_NAME + ".log"
CONFIG = []

# Configuration parameters to be applied to the inverter with initial/default values. 
# Actual values will be read from 'config.yaml'
UPDATE_INTERVAL = 120      # Update interval if used as service / from the console.
UPPER_CHARGING_LIMIT = 80  # Upper charging limit in %
SOE_DELTA_CHARGE = 5       # When the SOE drops by this amount of %, start charging again
BACKUP_RESERVE = 10        # Charge in % reserved only for backup + SE Home Batteries 48V has 10% reserved energy which cannot be changed/used
CHARGE_LIMIT = 5000        # Battery maximum charge power in W


def read_config(default=False):
    """
    Reading the configuration parameters from config.yaml file and
    sets the configuration in the respective global variables.

    :param default: When the default=True it reads the default config section.
    When False it read the configuration parameters for the period which fits for the current date

    :return: None
    """
    global CONFIG
    global LOGGER_LEVEL
    global UPDATE_INTERVAL
    global UPPER_CHARGING_LIMIT
    global SOE_DELTA_CHARGE
    global BACKUP_RESERVE
    global CHARGE_LIMIT

    with open('config.yaml', 'r') as file:
        CONFIG = yaml.safe_load(file)

    if default:
        UPDATE_INTERVAL = CONFIG["defaul_config"]["update_interval"]
        UPPER_CHARGING_LIMIT = CONFIG["defaul_config"]["upper_charging_limit"]
        SOE_DELTA_CHARGE = CONFIG["defaul_config"]["soe_delta_charge"]
        BACKUP_RESERVE = CONFIG["defaul_config"]["backup_reserve"]
        CHARGE_LIMIT = CONFIG["defaul_config"]["charge_limit"]
        log_config()
        return

    periods = CONFIG["periods"]

    for period in periods:
        today_datetime = datetime.today()
        period_start = period["period_start"].split("-")
        period_end = period["period_end"].split("-")
        period_start_datetime = datetime.strptime(
            f"{period_start[1]} {period_start[0]}, {today_datetime.year}", "%b %d, %Y"
        )
        period_end_datetime = datetime.strptime(
            f"{period_end[1]} {period_end[0]}, {today_datetime.year} 23:59:59", "%b %d, %Y %H:%M:%S"
        )

        if period_start_datetime <= today_datetime <= period_end_datetime:
            UPPER_CHARGING_LIMIT = period["config"]["upper_charging_limit"]
            SOE_DELTA_CHARGE = period["config"]["soe_delta_charge"]
            BACKUP_RESERVE = period["config"]["backup_reserve"]
            CHARGE_LIMIT = period["config"]["charge_limit"]
            log_config()


def log_config():
    """
    Log the current configuration parameters

    :return: None
    """
    LOGGER.debug(f"UPDATE_INTERVAL = {UPDATE_INTERVAL}")
    LOGGER.debug(f"UPPER_CHARGING_LIMIT = {UPPER_CHARGING_LIMIT}")
    LOGGER.debug(f"SOE_DELTA_CHARGE = {SOE_DELTA_CHARGE}")
    LOGGER.debug(f"BACKUP_RESEVE = {BACKUP_RESERVE}")
    LOGGER.debug(f"CHARGE_LIMIT = {CHARGE_LIMIT}")


def read_values():
    """
    Read all values/settings from the inverter

    :return: None
    """
    values = inverter.read_all()
    meters = inverter.meters()
    batteries = inverter.batteries()
    values["meters"] = {}
    values["batteries"] = {}
    values["storage"] = storage.read_all()

    for meter, params in meters.items():
        meter_values = params.read_all()
        values["meters"][meter] = meter_values

    for battery, params in batteries.items():
        battery_values = params.read_all()
        values["batteries"][battery] = battery_values

    return values


def set_storage_control_mode(val=4, retries=3):
    """
    Set "storage_contol_mode" (0xE004) - storage control mode
      0: "Disabled"
      1: "Maximize Self Consumption"
      2: "Time of Use"
      3: "Backup Only"
      4: "Remote Control"

    :param val: The new value to be set

    :param retries: Number of retires in case writing fails
    Retrying is a workaround till the issue in the 'solaredge_modbus' library if fixed.
    On a second attempt often the writing to the register succeeds.
    GitHub issue: https://github.com/nmakel/solaredge_modbus/issues/36

    :return: None
    """

    try:
        retry_count = retries
        while retry_count > 0:
            if not inverter.connected():
                inverter.connect()
            retry_count = retry_count - 1
            reg_query = storage.write("storage_control_mode", val)
            reg_result = storage.read("storage_control_mode")

            if is_response_exception(reg_query):
                LOGGER.error(f"Setting \"storage_control_mode\" (0xE004) to {val}. Error: " + str(reg_query.message))
                LOGGER.info(f"Retrying write to register...{retries - retry_count + 1} of {retries}")
                if retry_count == 0:
                    raise Exception(str(reg_query.message))
                else:
                    # Wait a bit before the next retry
                    LOGGER.info("Waiting for 10 sec. before the next retry...")
                    time.sleep(10)
            else:
                verify_register_write("storage_control_mode", val, reg_query, reg_result)
                break
    except Exception as err:
        LOGGER.error(f"Setting \"storage_control_mode\" (0xE004) to {val}.")
        LOGGER.exception(err, stack_info=True, exc_info=True)


def set_storage_backup_reserved(val=10, retries=3):
    """
    Set "storage_backup_reserved" (0xE008) - storage backup reserved capacity (%)

    :param val: The new value to be set

    :param retries: Number of retires in case writing fails
    Retrying is a workaround till the issue in the 'solaredge_modbus' library if fixed.
    On a second attempt often the writing to the register succeeds.
    GitHub issue: https://github.com/nmakel/solaredge_modbus/issues/36

    :return: None
    """

    try:
        retry_count = retries
        while retry_count > 0:
            if not inverter.connected():
                inverter.connect()
            retry_count = retry_count - 1
            reg_query = storage.write("storage_backup_reserved_setting", val)
            reg_result = storage.read("storage_backup_reserved_setting")

            if is_response_exception(reg_query):
                LOGGER.error(
                    f"Setting \"storage_backup_reserved_setting\" (0xE008) to {val}%. Error: " + str(reg_query.message))
                LOGGER.info(f"Retrying write to register...{retries - retry_count + 1} of {retries}")
                if retry_count == 0:
                    raise Exception(str(reg_query.message))
                else:
                    # Wait a bit before the next retry
                    LOGGER.info("Waiting for 10 sec. before the next retry...")
                    time.sleep(10)
            else:
                verify_register_write("storage_backup_reserved_setting", val, reg_query, reg_result)
                break
    except Exception as err:
        LOGGER.error(f"Setting \"storage_backup_reserved_setting\" (0xE008) to {val}%.")
        LOGGER.exception(err, stack_info=True, exc_info=True)


def set_storage_default_mode(val=7, retries=3):
    """
    Set "storage_default_mode" (0xE00A) - storage charge / discharge default mode
      0: "Off"
      1: "Charge from excess PV power only"
      2: "Charge from PV first"
      3: "Charge from PV and AC"
      4: "Maximize export"
      5: "Discharge to match load"
      7: "Maximize self consumption"

    :param val: The new value to be set

    :param retries: Number of retires in case writing fails
    Retrying is a workaround till the issue in the 'solaredge_modbus' library if fixed.
    On a second attempt often the writing to the register succeeds.
    GitHub issue: https://github.com/nmakel/solaredge_modbus/issues/36

    :return: None
    """

    try:
        retry_count = retries
        while retry_count > 0:
            if not inverter.connected():
                inverter.connect()
            retry_count = retry_count - 1
            reg_query = storage.write("storage_default_mode", val)
            reg_result = storage.read("storage_default_mode")

            if is_response_exception(reg_query):
                LOGGER.error(f"Setting \"storage_default_mode\" (0xE00A) to {val}. Error: " + str(reg_query.message))
                LOGGER.info(f"Retrying write to register...{retries - retry_count + 1} of {retries}")
                if retry_count == 0:
                    raise Exception(str(reg_query.message))
                else:
                    # Wait a bit before the next retry
                    LOGGER.info("Waiting for 10 sec. before the next retry...")
                    time.sleep(10)
            else:
                verify_register_write("storage_default_mode", val, reg_query, reg_result)
                break
    except Exception as err:
        LOGGER.error(f"Setting \"storage_default_mode\" (0xE00A) to {val}.")
        LOGGER.exception(err, stack_info=True, exc_info=True)


def set_rc_charge_limit(val=5000):
    """
    Set "rc_charge_limit" (0xE00E)

    :param val: The new value to be set

    :return: None
    """

    try:
        reg_query = storage.write("rc_charge_limit", val)
        reg_result = storage.read("rc_charge_limit")

        if is_response_exception(reg_query):
            LOGGER.error(f"Setting \"rc_charge_limit\" (0xE00E) to {val}Wh. Error: " + str(reg_query.message))
            return

        verify_register_write("rc_charge_limit", val, reg_query, reg_result)
    except Exception as err:
        LOGGER.error(f"Setting \"rc_charge_limit\" (0xE00E) to {val}Wh.")
        LOGGER.exception(err, stack_info=True, exc_info=True)


def set_rc_discharge_limit(val=5000):
    """
    Set "rc_discharge_limit" (0xE010)

    :param val: The new value to be set

    :return: None
    """

    try:
        reg_query = storage.write("rc_discharge_limit", val)
        reg_result = storage.read("rc_discharge_limit")

        if is_response_exception(reg_query):
            LOGGER.error(f"Setting \"rc_discharge_limit\" (0xE010) to {val}Wh. Error: " + str(reg_query.message))
            return

        verify_register_write("rc_discharge_limit", val, reg_query, reg_result)
    except Exception as err:
        LOGGER.error(f"Setting \"rc_discharge_limit\" (0xE010) to {val}Wh.")
        LOGGER.exception(err, stack_info=True, exc_info=True)


def set_rc_cmd_timeout(val=3600):
    """
    Set "rc_cmd_timeout" (0xE00B) - storage remote command timeout in seconds

    :param val: The new value to be set

    :return: None
    """

    try:
        reg_query = storage.write("rc_cmd_timeout", val)
        reg_result = storage.read("rc_cmd_timeout")

        if is_response_exception(reg_query):
            LOGGER.error(f"Setting \"rc_cmd_timeout\": {val} sec. Error: " + str(reg_query.message))
            return

        verify_register_write("rc_cmd_timeout", val, reg_query, reg_result)
    except Exception as err:
        LOGGER.error(f"Setting \"rc_cmd_timeout\": {val} sec.")
        LOGGER.exception(err, stack_info=True, exc_info=True)


def set_rc_cmd_mode(val=0):
    """
    Set "rc_cmd_mode" (0xE00D) - storage remote command mode
      0: "Off"
      1: "Charge from excess PV power only"
      2: "Charge from PV first"
      3: "Charge from PV and AC"
      4: "Maximize export"
      5: "Discharge to match load"
      7: "Maximize self consumption"

    :param val: The new value to be set

    :return: None
    """

    try:
        reg_query = storage.write("rc_cmd_mode", val)
        reg_result = storage.read("rc_cmd_mode")

        if is_response_exception(reg_query):
            LOGGER.error(f"Set \"rc_cmd_mode\" (0xE00A) to {val}. Error: " + str(reg_query.message))
            return

        verify_register_write("rc_cmd_mode", val, reg_query, reg_result)
    except Exception as err:
        LOGGER.error(f"Set \"rc_cmd_mode\" (0xE00A) to {val}.")
        LOGGER.exception(err, stack_info=True, exc_info=True)


def is_response_exception(reg_query):
    """
    Check whether the PyModBus response contains exception

    :param reg_query: PyModBus response to be checked

    :return: None
    """

    if type(reg_query) is (pymbEx.ModbusIOException or
                           pymbEx.ConnectionException or
                           pymbEx.InvalidMessageReceivedException or
                           pymbEx.ModbusException or
                           pymbEx.NoSuchSlaveException or
                           pymbEx.ParameterException or
                           pymbEx.MessageRegisterException or
                           pymbEx.NotImplementedException):
        return True
    else:
        return False


def verify_register_write(register_name, exp_val, reg_query, reg_result):
    """
    Verify the result of a write query according to official documentation:
    https://pymodbus.readthedocs.io/en/v1.3.2/examples/synchronous-client.html

    :param register_name: Register name to be verified
    :param exp_val: Expected value
    :param reg_query: Register query object (write return object)
    :param reg_result: Register response object reference (read return object)

    :return: None
    """

    func_code = reg_query.function_code
    if func_code >= 0x80:
        LOGGER.error(f"Error writing to register \"{register_name}\". " +
                     f"Returned \"function_code\" is {func_code}. Should below 128 (0x80).")
        return False

    reg_val = reg_result[register_name]
    if reg_val != exp_val:
        LOGGER.critical(f"Written register value for \"{register_name}\" is {reg_val} and should have been {exp_val}")
        return False

    return True


# -------------------------------------------------------------------------------

def inverter_update_routine():
    """
    Routine run for updating the SolarEdge corresponding configuration parameters
    according to the values specified in the current / default period

    :return: None
    """

    read_config()  # Reads the config according to the periods
    inverter.connect()
    values = read_values()
    soe = values["batteries"]["Battery1"].get("soe")
    battery_capacity = values["batteries"]["Battery1"].get("rated_energy")
    battery_manufacturer = values["batteries"]["Battery1"].get("c_manufacturer")
    if battery_manufacturer == "SolarEdge":
        battery_capacity = round(battery_capacity / 0.9)
    charing_limit_15p = round(battery_capacity * 0.15, -2)
    rc_cmd_mode = values["storage"].get("rc_cmd_mode")
    rc_charge_limit = values["storage"].get("rc_charge_limit")
    storage_backup_reserved_setting = values["storage"].get("storage_backup_reserved_setting")

    if soe >= UPPER_CHARGING_LIMIT and rc_cmd_mode != 5:
        LOGGER.info(f"SoC {round(soe, 2)}%. Reached upper limit of {UPPER_CHARGING_LIMIT}%.")
        LOGGER.info("Setting \"rc_cmd_timeout\" to 8h.")
        set_rc_cmd_timeout(28800)  # 8 Hours
        LOGGER.info("Setting \"set_rc_cmd_mode\" to \"5: Discharge to match load\".")
        set_rc_cmd_mode(5)

    if soe < (UPPER_CHARGING_LIMIT - SOE_DELTA_CHARGE) and rc_cmd_mode != 7:
        LOGGER.info(f"SoC {round(soe, 2)}%. Dropped by delta of {SOE_DELTA_CHARGE}%.")
        LOGGER.info("Setting \"rc_cmd_timeout\" to 1h.")
        set_rc_cmd_timeout()
        LOGGER.info("Setting \"set_rc_cmd_mode\" to \"7: Maximize self consumption\".")
        set_rc_cmd_mode(7)

    # For the last 3%, reduce the charging power to 0.15C in order to increase stop charging accurancy
    if rc_charge_limit > charing_limit_15p and soe >= (UPPER_CHARGING_LIMIT - 3):
        LOGGER.info(f"Battery SoC is {round(soe, 2)}%. " +
                    f"Lowering charging power to {charing_limit_15p} W. (0.15C) in order to increase stop charging accurancy.")
        LOGGER.info(f"Current battery charge limit: {rc_charge_limit} W.")
        LOGGER.info(f"Setting battery charge limit to: {charing_limit_15p} W.")
        set_rc_charge_limit(charing_limit_15p)

    if rc_charge_limit != CHARGE_LIMIT and soe <= (UPPER_CHARGING_LIMIT - 5):
        LOGGER.info(f"Current battery charge limit: {rc_charge_limit} W.")
        LOGGER.info(f"Setting battery charge limit to: {CHARGE_LIMIT} W.")
        set_rc_charge_limit(CHARGE_LIMIT)

    if storage_backup_reserved_setting != BACKUP_RESERVE:
        LOGGER.info(f"Current backup reserve: {storage_backup_reserved_setting}%.")
        LOGGER.info(f"Setting backup reserve to: {BACKUP_RESERVE}%.")
        set_storage_backup_reserved(BACKUP_RESERVE)

    inverter.disconnect()


# -------------------------------------------------------------------------------

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("host", type=str, help="Modbus TCP address")
    arg_parser.add_argument("--port", type=int, default=1502, help="Modbus TCP port")
    arg_parser.add_argument("--timeout", type=int, default=1, help="Connection timeout")
    arg_parser.add_argument("--unit", type=int, default=1, help="Modbus device address")
    arg_parser.add_argument("--info", action="store_true", default=False, help="Print all inverter settings")

    arg_parser.add_argument(
      "--enable_storage_remote_control_mode", action="store_true", default=False,
      help="Set the \"storage_contol_mode\" to \"4. Remote Control\". " +
           "Neccessary for the storage profiles to be considered. It must be done once. " +
           "Check the status with --info. Only after successful operation the script will work.")

    arg_parser.add_argument(
      "--set_storage_default_mode", type=int, choices=[0, 1, 2, 3, 4, 5, 7], default=-1,
      help="Set the default storage charge / discharge default mode (\"storage_default_mode\"). " +
           "Following options are available: 0. Off; 1. Charge from excess PV power only; " +
           "2. Charge from PV first; 3. Charge from PV and AC; 4. Maximize export; " +
           "5. Discharge to match load; 7. Maximize self consumption. " +
           "When using the --enable_storage_remote_control_mode to enable the remote control of the storage control, " +
           "the \"storage_default_mode\" is set to \"7. Maximize self consumption\"."
    )

    args = arg_parser.parse_args()

    # Setup logging to console & file
    LOGGER = logging.getLogger("se_battery_control")
    LOGGER.setLevel(LOGGER_LEVEL)
    log_formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(filename)s::%(lineno)d: %(message)s")

    console = logging.StreamHandler()
    console.setLevel(LOGGER_LEVEL)
    console.setFormatter(log_formatter)
    LOGGER.addHandler(console)
    # Limiting Log to 5MB per file and maximum 20 files
    rotationLogHandler = RotatingFileHandler(LOG_FILE, mode='a', maxBytes=5 * 1024 * 1024,
                                             backupCount=20, encoding='utf-8', delay=0)
    rotationLogHandler.setFormatter(log_formatter)
    rotationLogHandler.setLevel(LOGGER_LEVEL)
    LOGGER.addHandler(rotationLogHandler)

    read_config(True)

    inverter = solaredge_modbus.Inverter(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        unit=args.unit
    )
    storage = solaredge_modbus.StorageInverter(parent=inverter)

    if args.info:
        values = read_values()
        # Don't log 'info' mode output into the log file - console output only
        print(json.dumps(values, indent=2))
        exit()

    if args.enable_storage_remote_control_mode:
        inverter.connect()
        set_storage_control_mode(4)
        set_storage_default_mode(7)
        inverter.disconnect()
        exit()

    if args.set_storage_default_mode != -1:
        inverter.connect()
        set_storage_default_mode(args.set_storage_default_mode)
        inverter.disconnect()
        exit()

    # In order to be used as CronJob - just runs once
    inverter_update_routine()

    # Alternately, an infinite loop can be used instead of CronJob - runs every UPDATE_INTERVAL
    # Installing it as a service in this case is recommended in order to have automatic restarts
    # Before the "solaredge_modbus" library is fixed to work good with the storage registers, better use CronJob
    #
    # while True:
    #   inverter_update_routine()
    #   time.sleep(UPDATE_INTERVAL)

    # -------------------------------------------------------------------------------
