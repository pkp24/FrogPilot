import base64
import hmac
import json
import math
import re
import threading
import time

from datetime import datetime
from flask import Blueprint, Response, abort, jsonify, request, send_file
from io import BytesIO

from cereal import car, messaging
from opendbc.can.parser import CANParser
from openpilot.common.conversions import Conversions as CV
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.car.toyota.carcontroller import LOCK_CMD, UNLOCK_CMD
from openpilot.system.hardware import HARDWARE
from openpilot.system.loggerd.config import get_available_bytes, get_used_bytes
from openpilot.system.version import get_build_metadata

from openpilot.frogpilot.selfdrive.car.toyota.door_control import create_door_command
from openpilot.frogpilot.common import frogpilot_paths, frogpilot_utilities, frogpilot_variables
from openpilot.frogpilot.system.the_pond.helpers import format_ordinal_date, is_paired, is_safe_display_name, json_body, pair_browser

blueprint = Blueprint("device", __name__)

NUMERIC_KEYS = {key for key, value, _, _ in frogpilot_variables.frogpilot_default_params if re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", value)}
NUMERIC_KEYS |= frogpilot_variables.EMPTY_DEFAULT_FLOAT_KEYS
PAIRING_ATTEMPTS = 10
PAIRING_WINDOW = 10 * 60
PARAM_KEYS = {
  "DiscordUsername", "DownloadableColors", "DownloadableDistanceIcons", "DownloadableIcons", "DownloadableSignals", "DownloadableSounds",
  "DownloadableWheels",
}
STATE_TIMEOUT = 3


class DeviceState:
  def __init__(self):
    self.door_lock = threading.Lock()
    self.favorites_lock = threading.Lock()
    self.pairing_lock = threading.Lock()
    self.params_lock = threading.Lock()
    self.request_lock = threading.Lock()
    self.tailscale_lock = threading.Lock()
    self.theme_lock = threading.Lock()
    self.tmux_lock = threading.Lock()

    self.pm = messaging.PubMaster(["thePondRequest"])
    self.process_state_sock = messaging.sub_sock("frogpilotProcessState", conflate=True)

    self.pairing_failures = []
    self.process_state = None
    self.snapshot = (None, False, True, 0)
    self.theme_download_request_time = 0

  def run(self):
    subscriber = messaging.SubMaster(["frogpilotCarState", "managerState"], poll="managerState")

    while True:
      try:
        subscriber.update(1000)
        onroad = frogpilot_variables.params.get("IsOnroad")
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

  def download_theme(self, component, theme):
    msg = messaging.new_message("thePondRequest")
    theme_download = msg.thePondRequest.request.init("downloadTheme", 1)[0]
    theme_download.component = component
    theme_download.theme = theme
    with self.request_lock:
      self.theme_download_request_time = msg.logMonoTime
      self.pm.send("thePondRequest", msg)

  def send_request(self, kind):
    msg = messaging.new_message("thePondRequest")
    setattr(msg.thePondRequest.request, kind, None)
    with self.request_lock:
      self.pm.send("thePondRequest", msg)

  def theme_download(self):
    with self.request_lock:
      msg = messaging.recv_one_or_none(self.process_state_sock)
      if msg is not None:
        self.process_state = msg

      if self.process_state is None:
        return self.theme_download_request_time != 0, None

      process_state = self.process_state.frogpilotProcessState
      return process_state.downloadThemeRequestTime < self.theme_download_request_time, process_state

  def theme_download_progress(self):
    pending, process_state = self.theme_download()
    if pending:
      return "Downloading..."
    if process_state is None:
      return ""
    return process_state.themeDownloadProgress

  def theme_download_running(self):
    pending, process_state = self.theme_download()
    if pending or process_state is None:
      return pending

    finished = process_state.themeDownloadFailedCount + process_state.themeDownloadSuccessCount >= process_state.themeDownloadCount
    stopped = process_state.themeDownloadProgress in ("Download cancelled...", "GitHub and GitLab are offline...")
    return not (finished or stopped)


state = DeviceState()


def is_driving():
  onroad = frogpilot_variables.params.get("IsOnroad")
  if onroad == b"0":
    return False

  previous_onroad, parked, _, updated = state.snapshot
  return onroad != b"1" or onroad != previous_onroad or not parked or time.monotonic() - updated > STATE_TIMEOUT


def logger_running():
  onroad, _, running, updated = state.snapshot
  if frogpilot_variables.params.get("IsOnroad") != onroad or time.monotonic() - updated > STATE_TIMEOUT:
    return True
  if running:
    return True

  if onroad == b"1":
    try:
      toggles = json.loads(frogpilot_variables.params_memory.get("FrogPilotToggles") or b"{}")
    except ValueError:
      return True
    return not isinstance(toggles, dict) or toggles.get("no_logging") is not True

  return onroad != b"0"


def car_params():
  value = frogpilot_variables.params.get("CarParamsPersistent")
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
  return configuration is not None and configuration.carName == "toyota"


def send_door_command(locked):
  parser = CANParser("toyota_nodsu_pt_generated", [("DOOR_LOCKS", 3)], bus=0)
  publisher = messaging.PubMaster(["sendcan"])
  subscriber = messaging.sub_sock("can", timeout=100)

  command = UNLOCK_CMD
  if locked:
    command = LOCK_CMD

  deadline = time.monotonic() + 10
  while time.monotonic() < deadline:
    if frogpilot_variables.params.get("IsOnroad") != b"0":
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
  if frogpilot_variables.params.get("IsOnroad") != b"0":
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
  return {"onroad": is_driving(), "paired": is_paired()}


@blueprint.post("/api/pair")
def pair():
  body = json_body({"code", "token"})

  with state.pairing_lock:
    now = time.monotonic()
    state.pairing_failures = [failure for failure in state.pairing_failures if now - failure < PAIRING_WINDOW]
    if len(state.pairing_failures) >= PAIRING_ATTEMPTS:
      abort(429, "Too many wrong codes. Wait 10 minutes, then try again.")

    if not frogpilot_variables.params.get_bool("ThePondPairing"):
      abort(409, "Pairing is turned off on the car. Turn on “Pairing Code” in the car's Navigation settings to pair this browser.")

    state.pairing_failures.append(now)

    code = body.get("code")
    pairing_code = frogpilot_variables.params.get("ThePondPairingCode")
    if not isinstance(code, str) or not pairing_code or not hmac.compare_digest(code.encode(), pairing_code):
      abort(403, "That code doesn't match the one in the car's Navigation settings.")

    state.pairing_failures.remove(now)

    name, token, options = pair_browser()

  if body.get("token") is True:
    return {"token": token}

  response = Response(status=204)
  response.set_cookie(name, token, **options)
  return response


@blueprint.get("/api/params")
def get_param():
  key = request.args.get("key")
  if key not in PARAM_KEYS:
    abort(403)
  return frogpilot_variables.params.get(key) or b""


def saved_keys():
  keys = json.loads(frogpilot_variables.params.get("SecOCKeys") or b"[]")
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
      frogpilot_variables.params.put("SecOCKeys", json.dumps(keys))
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

      frogpilot_variables.params.put("SecOCKeys", json.dumps(keys))

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
    frogpilot_variables.params.put("SecOCKey", value)

    if frogpilot_paths.SECOC_KEY_PATH.exists():
      frogpilot_paths.SECOC_KEY_PATH.write_text(value)

  return "", 204


@blueprint.post("/api/toggles/backup")
def backup_toggles():
  with state.params_lock:
    values = {key: (frogpilot_variables.params.get(key) or b"").decode("utf8", errors="replace") for key in sorted(frogpilot_utilities.backup_keys())}

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

  allowed = frogpilot_utilities.backup_keys()
  values = {frogpilot_variables.RENAMED_KEYS.get(key, key): value for key, value in values.items()}
  if any(key in allowed and key in NUMERIC_KEYS and value and not re.fullmatch(r"-?[0-9]{1,9}(\.[0-9]{1,30})?", value) for key, value in values.items()):
    abort(400, "Invalid backup data")
  try:
    values = {key: value.encode() for key, value in values.items() if key in allowed}
  except UnicodeError:
    abort(400, "Invalid backup data")

  with state.params_lock:
    for key, value in values.items():
      frogpilot_variables.params.put(key, value)

  state.send_request("updateToggles")
  return {"success": True, "message": "Toggles restored!"}


def reboot_after_reset(parameter):
  if frogpilot_variables.params.get("IsOnroad") == b"0":
    HARDWARE.reboot()
  else:
    frogpilot_variables.params.remove(parameter)


@blueprint.post("/api/toggles/<action>")
def reset_toggles(action):
  if action not in ("reset_default", "reset_stock"):
    abort(404)
  if frogpilot_variables.params.get("IsOnroad") != b"0":
    abort(423, "Toggle reset is only available while offroad")

  parameter = "DoToggleReset"
  if action == "reset_stock":
    parameter = "DoToggleResetStock"

  with state.params_lock:
    if frogpilot_variables.params.get_bool("DoToggleReset") or frogpilot_variables.params.get_bool("DoToggleResetStock"):
      abort(409, "A toggle reset is already in progress")

    cloudlog.warning(f"The Pond: {action} and reboot requested")
    frogpilot_variables.params.put_bool(parameter, True)
    threading.Timer(0.5, reboot_after_reset, args=(parameter,)).start()

  return {"message": "Resetting toggles and rebooting..."}


def drive_stats():
  if frogpilot_utilities.use_konik_server():
    drive_stats_key = "ApiCache_DriveStatsKonik"
  else:
    drive_stats_key = "ApiCache_DriveStats"

  stats = []
  for key in (drive_stats_key, "FrogPilotStats"):
    try:
      value = json.loads(frogpilot_variables.params.get(key) or b"{}")
    except ValueError:
      value = {}
    if not isinstance(value, dict):
      value = {}
    stats.append(value)

  metric = frogpilot_variables.params.get_bool("IsMetric")
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
  if branch in (frogpilot_variables.DEVELOPMENT_BRANCH, frogpilot_variables.TESTING_BRANCH, frogpilot_variables.VETTING_BRANCH):
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

  version_date = "Unknown"
  commit_date = metadata.openpilot.git_commit_date.split()
  if len(commit_date) >= 2:
    version_date = format_ordinal_date(datetime.strptime(commit_date[1], "%Y-%m-%d"))

  update = "No"
  if frogpilot_variables.params.get_bool("UpdaterFetchAvailable"):
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
