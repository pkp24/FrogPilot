#!/usr/bin/env python3
import datetime
import errno
import json
import math
import numpy as np
import os
import requests
import subprocess
import threading
import tomllib
import zipfile

from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import openpilot.system.sentry as sentry
from cereal import log
from openpilot.common.params import Params, ParamKeyType
from openpilot.common.realtime import set_core_affinity
from openpilot.selfdrive.car.interfaces import TORQUE_SUBSTITUTE_PATH
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths
from openpilot.system.version import get_build_metadata

from openpilot.frogpilot.common import frogpilot_paths, frogpilot_variables

NetworkType = log.DeviceState.NetworkType

running_threads = {}

locks = {
  "backup_settings": threading.Lock(),
  "backup_toggles": threading.Lock(),
  "capture_report": threading.Lock(),
  "download_models": threading.Lock(),
  "download_themes": threading.Lock(),
  "flash_panda": threading.Lock(),
  "load_conditional_ways": threading.Lock(),
  "lock_doors": threading.Lock(),
  "restore_settings": threading.Lock(),
  "send_stats": threading.Lock(),
  "update_checks": threading.Lock(),
  "update_maps": threading.Lock(),
  "update_openpilot": threading.Lock(),
  "upload_speed_limits": threading.Lock(),
  "write_speed_limits": threading.Lock()
}

def run_thread_with_lock(name, target, args=(), report=True):
  with locks[name]:
    if not running_threads.get(name, threading.Thread()).is_alive():
      def wrapped_target(*t_args):
        set_core_affinity([0, 1, 2, 3])
        if not PC:
          os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))

        try:
          target(*t_args)
        except Exception as exception:
          print(f"Error in thread '{name}': {exception}")
          if report:
            sentry.capture_exception(exception, crash_log=False)
      thread = threading.Thread(target=wrapped_target, args=args, daemon=True)
      thread.start()
      running_threads[name] = thread

def backup_keys():
  return {
    key for key, _, _, _ in frogpilot_variables.frogpilot_default_params
    if key not in frogpilot_variables.EXCLUDED_KEYS and key not in frogpilot_variables.BACKUP_EXCLUDED_KEYS
    and not frogpilot_variables.params.get_key_flag(key) & ParamKeyType.DONT_LOG
  }

@cache
def block_user():
  branch = get_build_metadata().channel
  return branch in (frogpilot_variables.DEVELOPMENT_BRANCH, frogpilot_variables.PR_BRANCH, frogpilot_variables.VETTING_BRANCH) and not frogs_go_moo()

def calculate_curve_speed(road_curvature, lateral_acceleration, roll_compensation):
  geometric_lateral_acceleration = np.maximum(lateral_acceleration + np.sign(road_curvature) * roll_compensation, 0)
  return np.maximum(np.sqrt(geometric_lateral_acceleration / np.maximum(np.abs(road_curvature), 1e-6)), frogpilot_variables.CRUISING_SPEED)

def calculate_distance_to_point(lat1, lon1, lat2, lon2):
  lat1_rad = math.radians(lat1)
  lon1_rad = math.radians(lon1)
  lat2_rad = math.radians(lat2)
  lon2_rad = math.radians(lon2)

  sin_delta_lat = math.sin((lat2_rad - lat1_rad) / 2)
  sin_delta_lon = math.sin((lon2_rad - lon1_rad) / 2)

  haversine = sin_delta_lat ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * sin_delta_lon ** 2
  haversine = min(1, max(0, haversine))

  angular_distance = 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))
  return frogpilot_variables.EARTH_RADIUS * angular_distance

def calculate_lane_widths(model_data):
  lane_lines = np.array([line.y for line in model_data.laneLines])
  road_edges = np.array([edge.y for edge in model_data.roadEdges])
  ego_lines = lane_lines[[1, 2]]

  lane_widths = np.median(np.abs(lane_lines[[0, 3]] - ego_lines), axis=1)
  road_edge_distances = np.median(np.abs(road_edges - ego_lines), axis=1)
  return lane_widths, road_edge_distances

def calculate_road_curvature(model_data, v_ego, lateral_acceleration, roll_compensation):
  velocity = np.asarray(model_data.velocity.x)
  road_curvature = np.where(velocity >= frogpilot_variables.MINIMUM_PLANNED_SPEED, np.asarray(model_data.orientationRate.z) / np.maximum(velocity, 1), 0)

  distance_to_point = np.concatenate(([0], np.cumsum(np.hypot(np.diff(model_data.position.x), np.diff(model_data.position.y)))))
  time_to_point = distance_to_point / max(v_ego, frogpilot_variables.CRUISING_SPEED)

  curve_speed = calculate_curve_speed(road_curvature, lateral_acceleration, roll_compensation)
  required_deceleration = (v_ego - curve_speed) / np.maximum(time_to_point, 1)
  index = np.argmax(required_deceleration) if required_deceleration.max() > 0 else np.argmin(curve_speed)

  return float(road_curvature[index]), float(time_to_point[index]), float(np.abs(road_curvature).max())

def calculate_taco_turn_speeds(orientation_rates, speeds, v_ego):
  curvatures = np.asarray(orientation_rates) / np.clip(speeds, 0.3, 100.0)
  max_lat_accel = np.interp(v_ego, [5, 10, 20], [1.5, 2.0, 3.0])
  return np.sqrt(max_lat_accel / (np.abs(curvatures) + 1e-3)) - 2.0

def clean_model_name(name):
  return (
    name.replace("🗺️", "")
    .replace("📡", "")
    .replace("👀", "")
    .replace("(Default)", "")
    .strip()
  )

def delete_file(path, print_error=True, report=True):
  path = Path(path)
  if path.is_file() or path.is_symlink():
    run_cmd(["sudo", "rm", "-f", str(path)], f"Deleted file: {path}", f"Failed to delete file: {path}", report=report)
  elif path.is_dir():
    run_cmd(["sudo", "rm", "-rf", str(path)], f"Deleted directory: {path}", f"Failed to delete directory: {path}", report=report)
  elif print_error:
    print(f"File not found: {path}")

def extract_zip(zip_file, extract_path):
  zip_file = Path(zip_file)
  extract_path = Path(extract_path)
  print(f"Extracting {zip_file} to {extract_path}")

  extract_root = extract_path.resolve()
  with zipfile.ZipFile(zip_file, "r") as zip_ref:
    for member in zip_ref.namelist():
      if not (extract_path / member).resolve().is_relative_to(extract_root):
        raise ValueError(f"Refusing to extract path outside destination: {member}")
    zip_ref.extractall(extract_path)

  zip_file.unlink()
  print(f"Extraction completed: {zip_file} has been removed")

@cache
def frogs_go_moo():
  return frogpilot_paths.FROGS_GO_MOO_PATH.is_file()

def get_downloaded_models(models, thneed_models):
  return [
    model for model in models
    if all((frogpilot_paths.MODELS_PATH / filename).is_file() for filename, _ in model_files(model, model in thneed_models))
  ]

def get_log_roots():
  return tuple(dict.fromkeys((Paths.log_root(raw=True), Paths.log_root(HD=True, raw=True), Paths.log_root(konik=True, raw=True))))

@cache
def get_model_lat_smooth_seconds(model):
  params = Params()
  models = (params.get("AvailableModels", encoding="utf-8") or "").split(",")
  lat_smooth_seconds = (params.get("ModelLatSmoothSeconds", encoding="utf-8") or "").split(",")
  return float(dict(zip(models, lat_smooth_seconds, strict=False)).get(model) or frogpilot_variables.LAT_SMOOTH_SECONDS)

@cache
def get_model_version(model):
  params = Params()
  models = (params.get("AvailableModels", encoding="utf-8") or "").split(",")
  model_versions = (params.get("ModelVersions", encoding="utf-8") or "").split(",")
  return dict(zip(models, model_versions, strict=False)).get(model) or frogpilot_variables.DEFAULT_MODEL_VERSION

@cache
def get_nnff_model_files():
  return [file.stem for file in frogpilot_paths.NNFF_MODELS_PATH.iterdir() if file.is_file()]

@cache
def get_nnff_substitutes():
  with open(TORQUE_SUBSTITUTE_PATH, "rb") as f:
    return tomllib.load(f)

def get_phoenix_time():
  return datetime.datetime.now().astimezone(ZoneInfo("America/Phoenix")).strftime("%B %d, %Y - %I:%M%p")

def has_preserve_attr(path, attribute, value):
  try:
    return os.getxattr(path, attribute) == value
  except OSError as error:
    if error.errno in (errno.ENODATA, errno.ENOENT):
      return False
    raise

def is_classic_model(model):
  return get_model_version(model) in frogpilot_variables.CLASSIC_MODEL_VERSIONS

def is_thread_alive(name):
  with locks[name]:
    return running_threads.get(name, threading.Thread()).is_alive()

def is_tinygrad_model(model):
  return get_model_version(model) not in frogpilot_variables.THNEED_MODEL_VERSIONS

def is_url_pingable(url, session=requests):
  headers = {"Accept": "*/*", "User-Agent": "frogpilot-ping-test/1.0 (https://github.com/FrogAi/FrogPilot)"}
  try:
    return session.head(url, headers=headers, timeout=10, allow_redirects=True).ok
  except Exception:
    return False

def join_thread(name):
  with locks[name]:
    thread = running_threads.get(name)

  if thread is not None:
    thread.join()

def load_json_file(path):
  path = Path(path)
  if not path.is_file():
    return {}

  try:
    with open(path) as file:
      data = json.load(file)
  except (OSError, json.JSONDecodeError):
    print(f"Failed to load JSON file: {path}")
    return {}

  if not isinstance(data, dict):
    print(f"Failed to load JSON file: {path}")
    return {}

  return data

def model_files(model, thneed):
  if thneed:
    return [(f"{model}.thneed", "model")]
  return [(f"{model}_{filename}", description) for filename, description in frogpilot_variables.TINYGRAD_FILES]

@cache
def nnff_supported(car_fingerprint):
  from openpilot.frogpilot.controls.lib.neural_network_feedforward import get_nn_model_path
  return get_nn_model_path(car_fingerprint, "") is not None

def on_unmetered_network(device_state):
  return not device_state.networkMetered and device_state.networkType in (NetworkType.ethernet, NetworkType.wifi)

def run_cmd(cmd, success_message, fail_message, env=None, report=True):
  try:
    result = subprocess.run(cmd, capture_output=True, check=True, env=env, text=True)
    print(success_message)
    return result.stdout.strip()
  except subprocess.CalledProcessError as exception:
    print(f"Command failed with error: {exception.stderr}")
    print(fail_message)
    if report:
      sentry.capture_exception(exception, crash_log=False, extras={"stderr": exception.stderr})
    return None
  except Exception as exception:
    print(f"Unexpected error occurred: {exception}")
    print(fail_message)
    if report:
      sentry.capture_exception(exception, crash_log=False)
    return None

def update_json_file(path, data):
  temp_path = f"{path}.tmp"
  with open(temp_path, "w") as file:
    file.write(json.dumps(data, separators=(",", ":")))
    file.flush()
    os.fsync(file.fileno())

  os.replace(temp_path, path)

@cache
def use_action_delay(model):
  return model in frogpilot_variables.ACTION_DELAY_MODELS

def use_classic_longitudinal(model):
  return get_model_version(model) in frogpilot_variables.THNEED_MODEL_VERSIONS or model in frogpilot_variables.PRE_TOMB_RAIDER_MODELS

@cache
def use_current_speed_stop(model):
  return model in frogpilot_variables.CURRENT_SPEED_STOP_MODELS

@cache
def use_desired_curvature_action(model):
  return get_model_version(model) == "v7"

@cache
def use_desired_curvature_head(model):
  return model in (Params().get("DesiredCurvatureHeadModels", encoding="utf-8") or "").split(",")

@cache
def use_konik_server():
  return frogpilot_paths.KONIK_PATH.is_file()

@cache
def use_min_stable_delay(model):
  return model in frogpilot_variables.MIN_STABLE_DELAY_MODELS

@cache
def use_model_lead_trajectory(model):
  return get_model_version(model) == "v9"

@cache
def use_navigation_model(model):
  return get_model_version(model) == "v1"

@cache
def use_speed_error_correction(model):
  return model in frogpilot_variables.PRE_TOMB_RAIDER_MODELS

def valid_map_match(map_match, location_mono_time):
  map_match_age = location_mono_time - map_match.get("location_mono_time", 0)
  return bool(map_match.get("way_id")) and isinstance(map_match.get("is_forward"), bool) and 0 <= map_match_age <= frogpilot_variables.MAP_MATCH_MAX_AGE_NS
