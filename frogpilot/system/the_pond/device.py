import base64
import json
import math
import re
import threading
import time

from datetime import datetime
from flask import Blueprint, abort, jsonify, request, send_file
from io import BytesIO

from cereal import car, messaging
from opendbc.can.parser import CANParser
from openpilot.common.conversions import Conversions as CV
from openpilot.common.params import ParamKeyType
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.car.toyota.carcontroller import LOCK_CMD, UNLOCK_CMD
from openpilot.system.hardware import HARDWARE
from openpilot.system.loggerd.config import get_available_bytes, get_used_bytes
from openpilot.system.version import get_build_metadata

from openpilot.frogpilot.selfdrive.car.toyota.door_control import create_door_command
from openpilot.frogpilot.selfdrive.ui.theme_manager import DOWNLOAD_PROGRESS_PARAM
from openpilot.frogpilot.common.frogpilot_variables import EXCLUDED_KEYS, frogpilot_default_params, params, params_memory, update_frogpilot_toggles
from openpilot.frogpilot.system.the_pond.helpers import format_ordinal_date, is_safe_display_name, json_body

blueprint = Blueprint("device", __name__)

PARAM_KEYS = {
  "DiscordUsername", "DownloadableColors", "DownloadableDistanceIcons", "DownloadableIcons", "DownloadableSignals", "DownloadableSounds",
  "DownloadableWheels", "IsMetric",
}
STATE_TIMEOUT = 3


class DeviceState:
  def __init__(self):
    self.door_lock = threading.Lock()
    self.favorites_lock = threading.Lock()
    self.params_lock = threading.Lock()
    self.tailscale_lock = threading.Lock()
    self.theme_lock = threading.Lock()
    self.tmux_lock = threading.Lock()

    self.snapshot = (None, False, True, 0)

  def run(self):
    subscriber = messaging.SubMaster(["frogpilotCarState", "managerState"])

    while True:
      try:
        subscriber.update(1000)
        onroad = params.get("IsOnroad")
        previous_onroad = self.snapshot[0]

        parked = False
        if onroad == previous_onroad and subscriber.alive["frogpilotCarState"] and subscriber.valid["frogpilotCarState"]:
          parked = bool(subscriber["frogpilotCarState"].isParked)

        running = True
        if onroad == previous_onroad and subscriber.alive["managerState"] and subscriber.valid["managerState"]:
          running = any(process.name == "loggerd" and (process.running or process.shouldBeRunning) for process in subscriber["managerState"].processes)

        self.snapshot = (onroad, parked, running, time.monotonic())
      except Exception:
        self.snapshot = (None, False, True, 0)
        cloudlog.exception("The Pond could not read device state")
        time.sleep(1)


state = DeviceState()


def is_driving():
  onroad = params.get("IsOnroad")
  if onroad == b"0":
    return False

  previous_onroad, parked, _, updated = state.snapshot
  return onroad != b"1" or onroad != previous_onroad or not parked or time.monotonic() - updated > STATE_TIMEOUT


def logger_running():
  onroad, _, running, updated = state.snapshot
  if params.get("IsOnroad") != onroad or time.monotonic() - updated > STATE_TIMEOUT:
    return True
  if running:
    return True

  if onroad == b"1":
    try:
      toggles = json.loads(params_memory.get("FrogPilotToggles") or b"{}")
    except ValueError:
      return True
    return not isinstance(toggles, dict) or toggles.get("no_logging") is not True

  return onroad != b"0"


def car_params():
  value = params.get("CarParamsPersistent")
  if not value:
    return None

  try:
    with car.CarParams.from_bytes(value) as reader:
      return reader.as_builder()
  except Exception:
    cloudlog.exception("The Pond could not read vehicle configuration")
    return None


def doors_supported():
  configuration = car_params()
  return configuration is not None and configuration.carName == "toyota" and HARDWARE.get_device_type() != "tici"


def send_door_command(locked):
  parser = CANParser("toyota_nodsu_pt_generated", [("DOOR_LOCKS", 3)], bus=0)
  publisher = messaging.PubMaster(["sendcan"])
  subscriber = messaging.sub_sock("can", timeout=100)

  command = UNLOCK_CMD
  if locked:
    command = LOCK_CMD

  deadline = time.monotonic() + 10
  while time.monotonic() < deadline:
    if params.get("IsOnroad") != b"0":
      abort(409, "Door control is only available when the car is off")

    message = create_door_command(command)
    publisher.send("sendcan", message)

    time.sleep(1)
    parser.update_strings(messaging.drain_sock_raw(subscriber, wait_for_one=True))
    if parser.can_valid and (parser.vl["DOOR_LOCKS"]["LOCK_STATUS"] == 0) == locked:
      return

  abort(504, "Timed out waiting for the doors to respond")


@blueprint.get("/api/doors_available")
def doors_available():
  return {"result": doors_supported()}


@blueprint.post("/api/doors/<action>")
def doors(action):
  if action not in ("lock", "unlock"):
    abort(404)
  if not doors_supported():
    abort(409, "Door control is not supported on this device")
  if params.get("IsOnroad") != b"0":
    abort(409, "Door control is only available when the car is off")

  if not state.door_lock.acquire(blocking=False):
    abort(409, "Another door command is already running")
  try:
    cloudlog.warning(f"The Pond: door {action} requested")
    send_door_command(action == "lock")
  except messaging.MultiplePublishersError:
    abort(409, "Another process is controlling the doors. Try again in a moment.")
  finally:
    state.door_lock.release()

  return {"message": f"Doors {action}ed!"}


@blueprint.get("/api/onroad")
def onroad_status():
  return {"onroad": is_driving()}


@blueprint.get("/api/params")
def get_param():
  key = request.args.get("key")
  if key not in PARAM_KEYS:
    abort(403)
  return params.get(key) or b""


@blueprint.get("/api/params_memory")
def get_memory_param():
  if request.args.get("key") != DOWNLOAD_PROGRESS_PARAM:
    abort(403)
  return params_memory.get(DOWNLOAD_PROGRESS_PARAM) or b""


@blueprint.post("/api/speed_limits")
def speed_limits():
  speed_limits = json.loads(params.get("SpeedLimits") or "[]")
  for limit in speed_limits:
    limit.pop("tile", None)

  return send_file(BytesIO(json.dumps(speed_limits).encode()), as_attachment=True, download_name="speed_limits.json", mimetype="application/json")


def saved_keys():
  keys = json.loads(params.get("SecOCKeys") or b"[]")
  if not isinstance(keys, list) or any(not isinstance(key, dict) for key in keys):
    raise ValueError("Saved security keys are invalid")
  return keys


def valid_key(value):
  return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{32}", value) is not None


@blueprint.get("/api/tsk_available")
def tsk_available():
  configuration = car_params()
  return {"result": configuration is not None and configuration.secOcRequired}


@blueprint.route("/api/tsk_keys", methods=["DELETE", "GET", "POST"])
def security_keys():
  with state.params_lock:
    keys = saved_keys()

    if request.method == "DELETE":
      name = request.args.get("name")
      if not name:
        abort(400, "Missing key name")

      keys = [key for key in keys if key.get("name") != name]
      params.put("SecOCKeys", json.dumps(keys))
    elif request.method == "POST":
      if request.content_length is not None and request.content_length > 32 * 1024:
        abort(413, "Key list is too large")

      submitted = request.get_json(silent=True)
      if not isinstance(submitted, list) or len(submitted) > 64:
        abort(400, "Invalid security key list")

      stored = {key.get("name"): key.get("value") for key in keys}
      keys = []
      names = set()

      for entry in submitted:
        if not isinstance(entry, dict) or set(entry) - {"name", "rename_from", "value"}:
          abort(400, "Invalid security key")

        name = entry.get("name")
        if not is_safe_display_name(name) or not name.strip() or name in names:
          abort(400, "Key names must be nonempty and unique")

        previous_name = entry.get("rename_from", name)
        if not isinstance(previous_name, str):
          abort(400, "Invalid previous key name")
        value = entry.get("value", stored.get(previous_name))
        if not valid_key(value):
          abort(400, "Key must be 32 hexadecimal characters")

        keys.append({"name": name, "value": value})
        names.add(name)

      params.put("SecOCKeys", json.dumps(keys))

    return jsonify([{"name": key.get("name"), "value_set": valid_key(key.get("value"))} for key in keys])


@blueprint.post("/api/tsk_key_set")
def apply_security_key():
  data = json_body({"name", "value"})
  with state.params_lock:
    value = data.get("value")
    if value is None:
      value = next((key.get("value") for key in saved_keys() if key.get("name") == data.get("name")), None)
    if not valid_key(value):
      abort(400, "Key must be 32 hexadecimal characters")

    configuration = car_params()
    if configuration is None or not configuration.secOcRequired:
      abort(409, "Security keys are not applicable to this vehicle")

    cloudlog.warning("The Pond: security key applied")
    params.put("SecOCKey", value)

  return "", 204


def backup_keys():
  return {key for key, _, _, _ in frogpilot_default_params if key not in EXCLUDED_KEYS and not params.get_key_flag(key) & ParamKeyType.DONT_LOG}


@blueprint.post("/api/toggles/backup")
def backup_toggles():
  with state.params_lock:
    values = {key: (params.get(key) or b"").decode("utf8", errors="replace") for key in sorted(backup_keys())}

  return send_file(BytesIO(json.dumps({"data": values}, indent=2).encode()),
                   as_attachment=True, download_name="toggle_backup.json", mimetype="application/json")


@blueprint.post("/api/toggles/restore")
def restore_toggles():
  values = json_body({"data"}).get("data")
  if isinstance(values, str):
    try:
      encoded = base64.b64decode(values, validate=True).decode()
      key = "s8#pL3*Xj!aZ@dWq"
      values = json.loads("".join(chr(ord(character) ^ ord(key[index % len(key)])) for index, character in enumerate(encoded)))
    except (ValueError, UnicodeError):
      abort(400, "Invalid backup data")

  if not isinstance(values, dict) or any(not isinstance(value, str) for value in values.values()):
    abort(400, "Invalid backup data")

  allowed = backup_keys()
  try:
    values = {key: value.encode() for key, value in values.items() if key in allowed}
  except UnicodeError:
    abort(400, "Invalid backup data")

  with state.params_lock:
    for key, value in values.items():
      params.put(key, value)

  update_frogpilot_toggles()
  return {"success": True, "message": "Toggles restored!"}


def reboot_after_reset(parameter):
  if params.get("IsOnroad") == b"0":
    HARDWARE.reboot()
  else:
    params.remove(parameter)


@blueprint.post("/api/toggles/<action>")
def reset_toggles(action):
  if action not in ("reset_default", "reset_stock"):
    abort(404)
  if params.get("IsOnroad") != b"0":
    abort(423, "Toggle reset is only available while offroad")

  parameter = "DoToggleReset"
  if action == "reset_stock":
    parameter = "DoToggleResetStock"

  with state.params_lock:
    if params.get_bool("DoToggleReset") or params.get_bool("DoToggleResetStock"):
      abort(409, "A toggle reset is already in progress")

    cloudlog.warning(f"The Pond: {action} and reboot requested")
    params.put_bool(parameter, True)
    threading.Timer(0.5, reboot_after_reset, args=(parameter,)).start()

  return {"message": "Resetting toggles and rebooting..."}


def drive_stats():
  stats = []
  for key in ("ApiCache_DriveStats", "FrogPilotStats"):
    try:
      value = json.loads(params.get(key) or b"{}")
    except ValueError:
      value = {}
    if not isinstance(value, dict):
      value = {}
    stats.append(value)

  metric = params.get_bool("IsMetric")
  distance_conversion = 1
  meter_conversion = CV.METER_TO_MILE
  unit = "miles"
  if metric:
    distance_conversion = CV.MPH_TO_KPH
    meter_conversion = 0.001
    unit = "kilometers"

  def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
      try:
        if math.isfinite(value):
          return value
      except OverflowError:
        pass
    return 0

  result = {}
  for timeframe in ("all", "week"):
    values = stats[0].get(timeframe, {})
    if not isinstance(values, dict):
      values = {}
    result[timeframe] = {
      "distance": number(values.get("distance")) * distance_conversion,
      "drives": number(values.get("routes")),
      "hours": number(values.get("minutes")) / 60,
      "unit": unit,
    }

  result["frogpilot"] = {
    "distance": number(stats[1].get("FrogPilotMeters")) * meter_conversion,
    "drives": number(stats[1].get("FrogPilotDrives")),
    "hours": number(stats[1].get("FrogPilotSeconds")) / 3600,
    "unit": unit,
  }

  return result


@blueprint.get("/api/stats")
def statistics():
  metadata = get_build_metadata()
  branch = metadata.channel
  if branch in ("FrogPilot-Development", "FrogPilot-Testing", "FrogPilot-Vetting"):
    environment = branch.removeprefix("FrogPilot-")
  elif metadata.release_channel:
    environment = "Release"
  elif metadata.tested_channel:
    environment = "Staging"
  else:
    environment = branch

  free = get_available_bytes()
  used = get_used_bytes()
  total = free + used
  percentage = 0
  if total:
    percentage = used / total * 100

  owner = metadata.openpilot.git_normalized_origin.split("/")
  maintainer = "unknown"
  if len(owner) >= 2:
    maintainer = owner[1]

  version_date = format_ordinal_date(datetime.strptime(metadata.openpilot.git_commit_date.split()[1], "%Y-%m-%d"))
  update = "No"
  if params.get_bool("UpdaterFetchAvailable"):
    update = "Yes"

  return {
    "diskUsage": [{"free": f"{free // 2**30} GB", "size": f"{total // 2**30} GB", "used": f"{used // 2**30} GB", "usedPercentage": f"{percentage:.2f}%"}],
    "driveStats": drive_stats(),
    "softwareInfo": {
      "branchName": branch,
      "buildEnvironment": environment,
      "commitHash": metadata.openpilot.git_commit,
      "commitUrl": f"https://{metadata.openpilot.git_normalized_origin}/commit/{metadata.openpilot.git_commit}",
      "forkMaintainer": maintainer,
      "updateAvailable": update,
      "versionDate": version_date,
    },
  }
