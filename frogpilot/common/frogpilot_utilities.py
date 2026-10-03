#!/usr/bin/env python3
import json
import math
import numpy as np
import requests
import subprocess
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile

from functools import cache
from pathlib import Path

import openpilot.system.sentry as sentry

from openpilot.frogpilot.common.frogpilot_variables import CRUISING_SPEED, DECEL_TIME_MARGIN, EARTH_RADIUS, KONIK_PATH, MINIMUM_PLANNED_SPEED

running_threads = {}

locks = {
  "backup_toggles": threading.Lock(),
  "capture_report": threading.Lock(),
  "download_all_models": threading.Lock(),
  "download_model": threading.Lock(),
  "download_theme": threading.Lock(),
  "flash_panda": threading.Lock(),
  "lock_doors": threading.Lock(),
  "send_stats": threading.Lock(),
  "update_checks": threading.Lock(),
  "update_maps": threading.Lock(),
  "update_openpilot": threading.Lock()
}

def run_thread_with_lock(name, target, args=(), report=True):
  with locks[name]:
    if not running_threads.get(name, threading.Thread()).is_alive():
      def wrapped_target(*t_args):
        try:
          target(*t_args)
        except urllib.error.HTTPError as error:
          print(f"HTTP error: {error}")
        except subprocess.CalledProcessError as error:
          print(f"CalledProcessError in thread '{name}': {error}")
        except Exception as exception:
          print(f"Error in thread '{name}': {exception}")
          if report:
            sentry.capture_exception(exception)
      thread = threading.Thread(target=wrapped_target, args=args, daemon=True)
      thread.start()
      running_threads[name] = thread

def calculate_curve_speed(road_curvature, lateral_acceleration, roll_compensation):
  geometric_lateral_acceleration = np.maximum(lateral_acceleration + np.sign(road_curvature) * roll_compensation, 0)
  return np.maximum(np.sqrt(geometric_lateral_acceleration / np.maximum(np.abs(road_curvature), 1e-6)), CRUISING_SPEED)

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
  return EARTH_RADIUS * angular_distance

def calculate_lane_width(lane, current_lane, road_edge=None):
  current_x = np.asarray(current_lane.x)
  current_y = np.asarray(current_lane.y)

  lane_y_interp = np.interp(current_x, np.asarray(lane.x), np.asarray(lane.y))
  distance_to_lane = np.median(np.abs(current_y - lane_y_interp))

  if road_edge is None:
    return float(distance_to_lane)

  road_edge_y_interp = np.interp(current_x, np.asarray(road_edge.x), np.asarray(road_edge.y))
  distance_to_road_edge = np.median(np.abs(current_y - road_edge_y_interp))

  if distance_to_road_edge < distance_to_lane:
    return 0.0

  return float(distance_to_lane)

def delete_file(path, print_error=True, report=True):
  path = Path(path)
  if path.is_file() or path.is_symlink():
    run_cmd(["sudo", "rm", "-f", str(path)], f"Deleted file: {path}", f"Failed to delete file: {path}", report=report)
  elif path.is_dir():
    run_cmd(["sudo", "rm", "-rf", str(path)], f"Deleted directory: {path}", f"Failed to delete directory: {path}", report=report)
  elif print_error:
    print(f"File not found: {path}")

def extract_tar(tar_file, extract_path):
  tar_file = Path(tar_file)
  extract_path = Path(extract_path)
  print(f"Extracting {tar_file} to {extract_path}")

  with tarfile.open(tar_file, "r:gz") as tar:
    tar.extractall(path=extract_path, filter="data")

  tar_file.unlink()
  print(f"Extraction completed: {tar_file} has been removed")

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

def is_url_pingable(url, session=requests):
  if not url:
    return False

  headers = {"User-Agent": "frogpilot-ping-test/1.0 (https://github.com/FrogAi/FrogPilot)"}
  try:
    response = session.head(url, headers=headers, timeout=10, allow_redirects=True)
    try:
      if response.status_code in (405, 501):
        response.close()
        response = session.get(url, headers=headers, timeout=10, allow_redirects=True, stream=True)

      return response.ok
    finally:
      response.close()

  except (requests.exceptions.ConnectionError, requests.exceptions.SSLError):
    return False
  except requests.exceptions.RequestException as error:
    print(f"{error.__class__.__name__} while pinging {url}: {error}")
    return False
  except Exception as exception:
    print(f"Unexpected error while pinging {url}: {exception}")
    return False

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

def run_cmd(cmd, success_message, fail_message, env=None, report=True):
  try:
    result = subprocess.run(cmd, capture_output=True, check=True, env=env, text=True)
    print(success_message)
    return result.stdout.strip()
  except subprocess.CalledProcessError as exception:
    print(f"Command failed with error: {exception.stderr}")
    print(fail_message)
    if report:
      sentry.capture_exception(exception.stderr)
    return None
  except Exception as exception:
    print(f"Unexpected error occurred: {exception}")
    print(fail_message)
    if report:
      sentry.capture_exception(exception)
    return None

def select_road_curvature(model_data, v_ego, allowed_lateral_acceleration, roll_compensation):
  velocity = np.asarray(model_data.velocity.x)

  road_curvature = np.where(velocity >= MINIMUM_PLANNED_SPEED, np.asarray(model_data.orientationRate.z) / np.maximum(velocity, 1), 0)
  absolute_curvature = np.abs(road_curvature)

  distance_to_point = np.concatenate(([0], np.cumsum(np.hypot(np.diff(model_data.position.x), np.diff(model_data.position.y)))))
  time_to_point = np.maximum(distance_to_point / max(v_ego, CRUISING_SPEED), 1)

  curve_speed = calculate_curve_speed(road_curvature, allowed_lateral_acceleration, roll_compensation)
  required_deceleration = (v_ego - curve_speed) / np.maximum(time_to_point - DECEL_TIME_MARGIN, 1)
  if required_deceleration.max() > 0:
    index = np.argmax(required_deceleration)
  elif roll_compensation != 0:
    index = np.argmin(curve_speed)
  else:
    index = np.argmax(absolute_curvature)

  return float(road_curvature[index]), float(time_to_point[index]), float(absolute_curvature.max())

def update_json_file(path, data):
  with open(path, "w") as file:
    json.dump(data, file, indent=2, sort_keys=True)

@cache
def use_konik_server():
  return KONIK_PATH.is_file()
