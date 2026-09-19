import json
import subprocess
import time

from openpilot.frogpilot.common.frogpilot_variables import MAPS_PATH, params, params_cache, params_memory

def update_maps(now):
  try:
    maps_selected = json.loads(params.get("MapsSelected", encoding="utf-8") or "{}")
  except json.JSONDecodeError:
    maps_selected = None

  if not isinstance(maps_selected, dict):
    params.remove("MapsSelected")
    params_cache.remove("MapsSelected")
    return

  if not (maps_selected.get("nations") or maps_selected.get("states")):
    return

  now = now.astimezone()

  day = now.day
  is_first = day == 1
  is_Sunday = now.weekday() == 6
  schedule = params.get_int("PreferredSchedule")

  last_maps_update = params.get("LastMapsUpdate", encoding="utf-8")
  maps_downloaded = MAPS_PATH.exists() and last_maps_update is not None

  if maps_downloaded and (schedule == 0 or (schedule == 1 and not is_Sunday) or (schedule == 2 and not is_first)):
    return

  suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
  todays_date = now.strftime(f"%B {day}{suffix}, %Y")

  if maps_downloaded and last_maps_update == todays_date:
    return

  if params.get("OSMDownloadProgress", encoding="utf-8") is not None:
    return

  params_memory.put("OSMDownloadLocations", json.dumps(maps_selected))

  while params_memory.get("OSMDownloadLocations", encoding="utf-8") is not None:
    time.sleep(1)

  download_progress = json.loads(params.get("OSMDownloadProgress", encoding="utf-8") or "{}")

  if download_progress.get("downloaded_files") == download_progress.get("total_files", 0) > 0:
    params.put("LastMapsUpdate", todays_date)

    subprocess.run(["pkill", "mapd"], check=False)

  params.remove("OSMDownloadProgress")
