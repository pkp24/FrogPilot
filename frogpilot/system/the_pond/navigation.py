import hashlib
import json
import math
import re

from flask import Blueprint, abort, jsonify, request, send_from_directory
from pathlib import Path

from openpilot.frogpilot.common.frogpilot_variables import params
from openpilot.frogpilot.system.the_pond.device import state
from openpilot.frogpilot.system.the_pond.helpers import is_safe_display_name, json_body

blueprint = Blueprint("navigation", __name__)

KEYS = {
  "amap1": ("AMapKey1", "", 39, "AMap key #1"),
  "amap2": ("AMapKey2", "", 39, "AMap key #2"),
  "public": ("MapboxPublicKey", "pk.", 80, "Public key"),
  "secret": ("MapboxSecretKey", "sk.", 80, "Secret key"),
}
MAPBOX_HELP_IMAGES = {"both_keys_set.png", "no_keys_set.png", "public_key_set.png", "setup_completed.png"}
NAVIGATION_TRAINING_PATH = Path(__file__).parents[2] / "selfdrive/assets/navigation/navigation_training"


def valid_coordinate(value, minimum, maximum):
  return isinstance(value, (int, float)) and not isinstance(value, bool) and minimum <= value <= maximum and math.isfinite(value)


def valid_mapbox_key(value, prefix):
  return re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value) is not None


def favorite_id(favorite):
  identity = f"{favorite.get('longitude')},{favorite.get('latitude')}|{favorite.get('routeId') or ''}|{favorite.get('name') or ''}"
  return hashlib.sha1(identity.encode()).hexdigest()


def favorites():
  stored = json.loads(params.get("FavoriteDestinations") or b"[]")
  if not isinstance(stored, list) or any(not isinstance(favorite, dict) for favorite in stored):
    raise ValueError("Saved favorites are invalid")

  for favorite in stored:
    favorite.setdefault("id", favorite_id(favorite))

  return stored


def favorite_data(fields):
  data = json_body(fields, 4096)
  if data.get("name") is not None and not is_safe_display_name(data["name"]):
    abort(400, "Invalid destination name")

  for field in ("id", "routeId"):
    if field in data and (not isinstance(data[field], str) or len(data[field]) > 256):
      abort(400, "Invalid favorite identifier")

  for field in ("is_home", "is_work"):
    if field in data and not isinstance(data[field], bool):
      abort(400, "Invalid favorite location type")
  if data.get("is_home") and data.get("is_work"):
    abort(400, "A destination cannot be both Home and Work")

  return data


@blueprint.route("/api/navigation", methods=["DELETE", "GET", "POST"])
def navigation():
  if request.method == "GET":
    try:
      position = json.loads(params.get("LastGPSPosition") or b"{}")
    except ValueError:
      position = {}

    last_position = None
    if isinstance(position, dict) and valid_coordinate(position.get("latitude"), -90, 90) and valid_coordinate(position.get("longitude"), -180, 180):
      last_position = {"latitude": str(position["latitude"]), "longitude": str(position["longitude"])}

    public_key = params.get("MapboxPublicKey", encoding="utf8") or ""
    if not valid_mapbox_key(public_key, "pk."):
      public_key = ""

    return {
      "amap1KeySet": bool(params.get("AMapKey1")),
      "amap2KeySet": bool(params.get("AMapKey2")),
      "destination": params.get("NavDestination", encoding="utf8") or "",
      "isMetric": params.get_bool("IsMetric"),
      "lastPosition": last_position,
      "mapboxPublic": public_key,
      "mapboxSecretSet": bool(params.get("MapboxSecretKey")),
      "previousDestinations": params.get("ApiCache_NavDestinations", encoding="utf8") or "",
    }

  if request.method == "DELETE":
    params.remove("NavDestination")
    params.remove("NavDestinationWaypoints")
    return {"message": "Destination cleared"}

  destination = favorite_data({"latitude", "longitude", "name"})
  if not valid_coordinate(destination.get("latitude"), -90, 90) or not valid_coordinate(destination.get("longitude"), -180, 180):
    abort(400, "Invalid destination coordinates")

  params.remove("NavDestinationWaypoints")
  params.put("NavDestination", json.dumps(destination))

  return {"message": "Destination sent to FrogPilot"}


@blueprint.route("/api/navigation/favorite", methods=["DELETE", "GET", "POST"])
def favorite_destinations():
  if request.method == "GET":
    with state.favorites_lock:
      return jsonify(favorites=favorites())

  favorite = favorite_data({"id", "is_home", "is_work", "latitude", "longitude", "name", "routeId"})

  with state.favorites_lock:
    saved = favorites()

    if request.method == "DELETE":
      if favorite.get("id"):
        saved = [entry for entry in saved if entry["id"] != favorite["id"]]
      else:
        saved = [entry for entry in saved if any(entry.get(field) != favorite.get(field) for field in ("latitude", "longitude", "name", "routeId"))]
      message = "Destination removed from favorites!"
    else:
      if (not is_safe_display_name(favorite.get("name")) or not valid_coordinate(favorite.get("latitude"), -90, 90)
          or not valid_coordinate(favorite.get("longitude"), -180, 180)):
        abort(400, "Invalid favorite name or coordinates")

      favorite.setdefault("id", favorite_id(favorite))
      if not any(entry["id"] == favorite["id"] for entry in saved):
        if len(saved) >= 100:
          abort(400, "A maximum of 100 favorites can be saved")

        for field in ("is_home", "is_work"):
          if favorite.get(field):
            for entry in saved:
              entry.pop(field, None)
        saved.append(favorite)

      message = "Destination added to favorites!"

    params.put("FavoriteDestinations", json.dumps(saved))

  return {"message": message}


@blueprint.post("/api/navigation/favorite/rename")
def rename_favorite():
  data = favorite_data({"id", "is_home", "is_work", "name", "routeId"})
  if not data.get("id") and not data.get("routeId"):
    abort(400, "Missing favorite identifier")

  with state.favorites_lock:
    saved = favorites()
    target = None
    for favorite in saved:
      if data.get("id"):
        matches = favorite["id"] == data["id"]
      else:
        matches = favorite.get("routeId") == data["routeId"]
      if matches:
        target = favorite
        break

    if target is None:
      abort(404, "Favorite not found")

    if data.get("name"):
      target["name"] = data["name"]

    for field, other in (("is_home", "is_work"), ("is_work", "is_home")):
      if field not in data:
        continue

      if data[field]:
        for favorite in saved:
          favorite.pop(field, None)
        target[field] = True
        target.pop(other, None)
      else:
        target.pop(field, None)

    params.put("FavoriteDestinations", json.dumps(saved))

  return {"message": "Favorite updated successfully!"}


@blueprint.route("/api/navigation_key", methods=["DELETE", "POST"])
def navigation_keys():
  if request.method == "DELETE":
    key = KEYS.get(request.args.get("type"))
    if key is None:
      abort(400, "Unknown key type")

    params.remove(key[0])
    return {"message": f"{key[3]} deleted successfully!"}

  data = json_body(set(KEYS))
  updates = []
  for key, (parameter, prefix, length, label) in KEYS.items():
    value = data.get(key, "")
    if not isinstance(value, str):
      abort(400, f"{label} must be text")

    value = value.strip()
    if not value:
      continue

    if prefix and not value.startswith(("pk.", "sk.")):
      value = prefix + value
    if prefix and not valid_mapbox_key(value, prefix):
      abort(400, f"Enter a valid {label.lower()} starting with {prefix}")
    if len(value) < length:
      abort(400, f"{label} is invalid or too short")
    updates.append((parameter, value, label))

  if not updates:
    abort(400, "Nothing to update")

  for parameter, value, _ in updates:
    params.put(parameter, value)

  return {"message": f"{', '.join(label for _, _, label in updates)} saved successfully!"}


@blueprint.get("/mapbox-help/<filename>")
def mapbox_help(filename):
  if filename not in MAPBOX_HELP_IMAGES:
    abort(404)

  return send_from_directory(NAVIGATION_TRAINING_PATH, filename)
