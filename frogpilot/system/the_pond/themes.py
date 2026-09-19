import json
import os
import re
import requests
import shutil
import subprocess
import tempfile

from contextlib import contextmanager
from pathlib import Path

from flask import Blueprint, abort, current_app, request, send_file
from PIL import Image
from werkzeug.utils import secure_filename

from openpilot.frogpilot.selfdrive.ui.theme_manager import (
  CANCEL_DOWNLOAD_PARAM, DOWNLOAD_PROGRESS_PARAM, HOLIDAY_THEME_PATH, POND_ACTIVE_THEME, STOCKOP_THEME_PATH, THEME_COMPONENT_PARAMS
)
from openpilot.frogpilot.common.frogpilot_api import ThemeAsset, ThemeSubmissionError
from openpilot.frogpilot.common.frogpilot_variables import ACTIVE_THEME_PATH, THEME_SAVE_PATH, params, params_memory, update_frogpilot_toggles
from openpilot.frogpilot.system.the_pond.device import state
from openpilot.frogpilot.system.the_pond.helpers import is_safe_slug, is_within, theme_asset_slug

blueprint = Blueprint("themes", __name__)

COLOR_NAMES = ("LaneLines", "LeadMarker", "Path", "PathEdge", "Sidebar1", "Sidebar2", "Sidebar3")
DISTANCE_ICONS = ("traffic", "aggressive", "standard", "relaxed")
IMAGE_FORMATS = {".png": "PNG", ".gif": "GIF", ".jpg": "JPEG", ".jpeg": "JPEG"}
SOUND_NAMES = ("startup", "prompt", "engage", "disengage")

COMPONENTS = {
  "colors": ("colors", "CustomColors", "hasColors"),
  "distance_icons": ("distance_icons", "CustomDistanceIcons", "hasDistanceIcons"),
  "icons": ("icons", "CustomIcons", "hasIcons"),
  "sounds": ("sounds", "CustomSounds", "hasSounds"),
  "steering_wheel": ("steering_wheels", "WheelIcon", "hasSteeringWheel"),
  "turn_signals": ("signals", "CustomSignals", "hasTurnSignals"),
}

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@blueprint.errorhandler(ValueError)
@blueprint.errorhandler(ThemeSubmissionError)
def invalid_theme(error):
  return {"error": str(error)}, 400


def display_name(name):
  name = name.replace("-user_created", "")
  parts = [part.capitalize() for part in re.split(r"[-_]", name)]
  if "-" in name and len(parts) > 1:
    return f"{parts[0]} ({' '.join(parts[1:])})".replace(" Week", "")
  return " ".join(parts).replace(" Week", "")


def image_file(directory, stem):
  for extension in IMAGE_FORMATS:
    path = directory / f"{stem}{extension}"
    if path.is_file():
      return path
  return None


def check_asset_path(path):
  if not any(is_within(root, path) for root in (ACTIVE_THEME_PATH, THEME_SAVE_PATH, HOLIDAY_THEME_PATH, STOCKOP_THEME_PATH)):
    abort(403, description="Invalid theme asset path")


def theme_directory(name, theme_type):
  root = THEME_SAVE_PATH / "theme_packs"
  if theme_type == "holiday":
    root = HOLIDAY_THEME_PATH

  directory = root / name
  if Path(name).name != name or directory.resolve().parent != root.resolve():
    abort(403, description="Invalid theme path")

  return directory


def read_theme(directory, wheel=None):
  data = {
    "colors": None,
    "images": {"distanceIcons": {}},
    "sounds": {},
    "sequentialImages": [],
    "turnSignalLength": 100,
    "turnSignalStyle": "Static",
    "turnSignalType": "Single Image",
  }

  colors = directory / "colors/colors.json"
  if colors.is_file():
    check_asset_path(colors)
    data["colors"] = json.loads(colors.read_text())

  for field, folder, stem in [
    ("homeButton", "icons", "button_home"), ("settingsButton", "icons", "button_settings"),
    ("turnSignal", "signals", "turn_signal"), ("turnSignalBlindspot", "signals", "turn_signal_blindspot"),
  ]:
    path = image_file(directory / folder, stem)
    if path:
      check_asset_path(path)
      data["images"][field] = {"filename": path.name, "path": f"{folder}/{path.name}"}

  for name in DISTANCE_ICONS:
    path = image_file(directory / "distance_icons", name)
    if path:
      check_asset_path(path)
      data["images"]["distanceIcons"][name] = {"filename": path.name, "path": f"distance_icons/{path.name}"}

  for name in SOUND_NAMES:
    path = directory / "sounds" / f"{name}.wav"
    if path.is_file():
      check_asset_path(path)
      data["sounds"][name] = {"filename": path.name, "path": f"sounds/{path.name}"}

  if wheel:
    check_asset_path(wheel)
    data["images"]["steeringWheel"] = {"filename": wheel.name, "path": f"{wheel.parent.name}/{wheel.name}"}

  signals = directory / "signals"
  if signals.is_dir():
    check_asset_path(signals)
    data["turnSignalStyle"] = "Traditional"

    for path in sorted(signals.iterdir()):
      if not path.is_file():
        continue

      check_asset_path(path)
      if path.suffix.lower() in IMAGE_FORMATS and re.fullmatch(r"turn_signal_\d+", path.stem):
        data["sequentialImages"].append(path.name)

      marker = re.fullmatch(r"(static|traditional)_(\d+)", path.name)
      if marker:
        data["turnSignalStyle"] = marker[1].capitalize()
        data["turnSignalLength"] = int(marker[2])

    if data["sequentialImages"]:
      data["turnSignalType"] = "Sequential"

  return data


@blueprint.get("/api/themes/default")
def current_theme():
  wheel = image_file(ACTIVE_THEME_PATH / "steering_wheel", "wheel")
  data = read_theme(ACTIVE_THEME_PATH, wheel)

  for key, asset in data["images"].items():
    if key == "distanceIcons":
      data["images"][key] = {name: item["filename"] for name, item in asset.items()}
    else:
      data["images"][key] = asset["filename"]
  data["sounds"] = {name: item["filename"] for name, item in data["sounds"].items()}

  data["theme_names"] = {}
  personalized = params.get_bool("PersonalizeOpenpilot")
  for component, (_, parameter, _) in COMPONENTS.items():
    key = {"distance_icons": "distanceIcons", "steering_wheel": "steeringWheel", "turn_signals": "turnSignals"}.get(component, component)
    data["theme_names"][key] = "Stock"
    if personalized:
      data["theme_names"][key] = display_name(params.get(parameter, encoding="utf-8") or "Stock")

  return data


@blueprint.get("/api/themes/list")
def list_themes():
  themes = []
  for root, theme_type in [(THEME_SAVE_PATH / "theme_packs", "standard"), (HOLIDAY_THEME_PATH, "holiday")]:
    if not root.is_dir():
      continue

    for directory in root.iterdir():
      if not directory.is_dir() or directory.is_symlink() or directory.name == POND_ACTIVE_THEME:
        continue

      created = theme_type != "holiday" and directory.name.endswith("-user_created")
      entry = {"name": display_name(directory.name), "path": directory.name, "type": theme_type, "is_user_created": created}
      if created:
        entry["type"] = "user"

      for component, (folder, _, flag) in COMPONENTS.items():
        if component == "steering_wheel":
          entry[flag] = theme_type == "holiday" and image_file(directory / "steering_wheel", "wheel") is not None
        elif component == "colors":
          entry[flag] = (directory / "colors/colors.json").is_file()
        else:
          entry[flag] = (directory / folder).is_dir() and any((directory / folder).iterdir())
      themes.append(entry)

  wheels = THEME_SAVE_PATH / "steering_wheels"
  if wheels.is_dir():
    for wheel in wheels.iterdir():
      if not wheel.is_file() or wheel.is_symlink() or wheel.suffix.lower() not in IMAGE_FORMATS or wheel.stem == POND_ACTIVE_THEME:
        continue

      themes.append({
        "name": display_name(wheel.stem), "path": wheel.name, "type": "steering_wheel",
        "is_user_created": wheel.stem.endswith("-user_created"), "hasSteeringWheel": True,
      })

  return {"themes": sorted(themes, key=lambda theme: theme["name"].casefold())}


@blueprint.get("/api/themes/load/<path:theme>")
def load_theme(theme):
  theme_type = request.args.get("type", "")
  directory = theme_directory(theme, theme_type)
  wheel = image_file(THEME_SAVE_PATH / "steering_wheels", theme)
  if theme_type == "holiday":
    wheel = image_file(directory / "steering_wheel", "wheel")
  if not directory.is_dir() and wheel is None:
    abort(404, description="Theme not found")

  return read_theme(directory, wheel)


@blueprint.get("/api/themes/asset/<path:theme>/<path:asset_path>")
def theme_asset(theme, asset_path):
  relative = Path(asset_path)
  if relative.suffix.lower() not in {*IMAGE_FORMATS, ".wav", ".json"} or relative.is_absolute() or ".." in relative.parts:
    abort(404)

  if theme == "__active__" or request.args.get("type") == "active":
    root = ACTIVE_THEME_PATH
  elif relative.parts[0] == "steering_wheels":
    root = THEME_SAVE_PATH
  else:
    root = theme_directory(theme, request.args.get("type", ""))

  path = root / relative
  if not is_within(root, path):
    # Active components are symlinks managed by ThemeManager into either of these roots.
    if root != ACTIVE_THEME_PATH or not any(is_within(base, path) for base in (THEME_SAVE_PATH, HOLIDAY_THEME_PATH, STOCKOP_THEME_PATH)):
      abort(403)
  if not path.is_file():
    abort(404)

  return send_file(path)


def validate_theme(form, files, applying=False):
  name = secure_filename((form.get("themeName") or "").strip().replace(" ", "_"))
  if applying:
    name = POND_ACTIVE_THEME.removesuffix("-user_created")
  if not name or (not applying and f"{name}-user_created" == POND_ACTIVE_THEME):
    raise ValueError("A valid theme name is required.")

  try:
    checklist = json.loads(form.get("saveChecklist", "{}"))
  except (ValueError, TypeError):
    raise ValueError("Select the components to use.") from None
  if not isinstance(checklist, dict) or any(key not in COMPONENTS or not isinstance(value, bool) for key, value in checklist.items()):
    raise ValueError("Invalid component selection.")
  selected = [component for component in COMPONENTS if checklist.get(component)]
  if not selected:
    raise ValueError("Select at least one component.")

  colors = None
  if "colors" in selected:
    try:
      colors = json.loads(form.get("colors", ""))
    except (ValueError, TypeError):
      raise ValueError("Theme colors are invalid.") from None
    if not isinstance(colors, dict) or set(colors) != set(COLOR_NAMES):
      raise ValueError("The seven theme colors are required.")

    for color in colors.values():
      if not isinstance(color, dict) or set(color) != {"red", "green", "blue", "alpha"}:
        raise ValueError("Theme color channels are invalid.")
      if any(type(channel) is not int or not 0 <= channel <= 255 for channel in color.values()):
        raise ValueError("Theme color channels must be integers from 0 to 255.")

  style = form.get("turnSignalStyle", "Traditional")
  signal_type = form.get("turnSignalType", "Single Image")
  interval = form.get("turnSignalLength", "100")
  if "turn_signals" in selected:
    if style not in ("Static", "Traditional") or signal_type not in ("Single Image", "Sequential"):
      raise ValueError("Invalid turn signal style or type.")
    if not isinstance(interval, str) or not interval.isdecimal() or not 25 <= int(interval) <= 1000:
      raise ValueError("Turn signal timing must be from 25 to 1000 ms.")

  for field, upload in files.items(multi=True):
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > MAX_UPLOAD_BYTES:
      raise ValueError(f"File {upload.filename} exceeds the 5 MiB limit.")
    if len(files.getlist(field)) != 1:
      raise ValueError("Duplicate upload fields are not supported.")

  return name, selected, colors, style, signal_type, interval


def remove_path(path):
  if path.is_dir() and not path.is_symlink():
    shutil.rmtree(path)
  elif os.path.lexists(path):
    path.unlink()


def real_directory(path):
  if path.is_symlink() or (path.exists() and not path.is_dir()):
    raise ValueError("Theme folders must be real directories.")

  path.mkdir(parents=True, exist_ok=True)


def validate_image(upload, sequential=False):
  extension = Path(upload.filename).suffix.lower()
  if extension not in IMAGE_FORMATS or (sequential and extension == ".gif"):
    raise ValueError("Choose a PNG or JPEG sequence frame." if sequential else "Choose a PNG, JPEG or GIF image.")

  try:
    upload.stream.seek(0)
    with Image.open(upload.stream) as image:
      if image.format != IMAGE_FORMATS[extension]:
        raise ValueError(f"File {upload.filename} does not match its image extension.")
      image.verify()
  except (OSError, SyntaxError, Image.DecompressionBombError) as error:
    raise ValueError(f"File {upload.filename} is not a valid image.") from error
  finally:
    upload.stream.seek(0)

  return extension


def save_image(upload, directory, stem, dimensions=None, sequential=False):
  extension = validate_image(upload, sequential)
  for previous in directory.glob(f"{stem}.*"):
    remove_path(previous)

  path = directory / f"{stem}{extension}"
  upload.save(path)

  if extension == ".gif":
    if dimensions:
      palette = directory / f"{stem}.palette.png"
      resized = directory / f"{stem}.resized.gif"
      subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vf", "palettegen", "-y", str(palette)], check=True, timeout=600)
      subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-i", str(palette), "-lavfi",
        f"fps=20,scale={dimensions[0]}:{dimensions[1]}:flags=lanczos[x];[x][1:v]paletteuse", "-y", str(resized),
      ], check=True, timeout=600)
      palette.unlink()
      resized.replace(path)
    return path

  with Image.open(path) as image:
    if dimensions:
      image = image.resize(dimensions, Image.Resampling.LANCZOS)
    if image.mode == "CMYK":
      image = image.convert("RGB")
    output = path.with_suffix(".png")
    image.save(output, "PNG")
  if output != path:
    path.unlink()

  return output


def save_sound(upload, directory, name):
  source = directory / f".{name}.upload"
  upload.save(source)

  try:
    result = subprocess.run([
      "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(source),
      "-map", "0:a:0", "-vn", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", "-y", str(directory / f"{name}.wav"),
    ], capture_output=True, timeout=600)
    if result.returncode:
      raise ValueError(f"File {upload.filename} could not be decoded as audio.")
  finally:
    source.unlink()


def prepare_theme(stage, validated, files, merge):
  name, selected, colors, style, signal_type, interval = validated
  outputs = []
  for component in selected:
    folder = COMPONENTS[component][0]
    if component == "steering_wheel":
      upload = files.get("steeringWheel")
      if not upload or not upload.filename:
        raise ValueError("Choose a steering wheel image.")

      directory = stage / "new/steering_wheels"
      directory.mkdir(parents=True, exist_ok=True)
      if merge:
        wheel = save_image(upload, directory, f"{name}-user_created", (250, 250))
      else:
        extension = validate_image(upload)
        wheel = directory / f"{name}-user_created{extension}"
        upload.save(wheel)

      live = THEME_SAVE_PATH / "steering_wheels" / wheel.name
      if merge:
        for previous in live.parent.glob(f"{name}-user_created.*"):
          if previous != live:
            outputs.append((None, previous))
      outputs.append((wheel, live))
      continue

    relative = Path("theme_packs") / f"{name}-user_created" / folder
    directory = stage / "new" / relative
    live = THEME_SAVE_PATH / relative

    if merge:
      for parent in reversed(relative.parents):
        real_directory(THEME_SAVE_PATH / parent)
    if merge and os.path.lexists(live):
      if live.is_symlink() or not live.is_dir():
        raise ValueError("Existing theme components must be real directories.")
      shutil.copytree(live, directory, symlinks=True)
      if any(path.is_symlink() for path in directory.rglob("*")):
        raise ValueError("Existing theme components cannot contain symbolic links.")
    else:
      directory.mkdir(parents=True, exist_ok=True)

    if component == "colors":
      (directory / "colors.json").write_text(json.dumps(colors, indent=2))
    elif component == "turn_signals":
      for previous in directory.iterdir():
        if previous.name.startswith("turn_signal") or previous.suffix.lower() not in IMAGE_FORMATS:
          remove_path(previous)

      (directory / f"{style.lower()}_{interval}").touch()
      if signal_type == "Sequential":
        fields = [field for field in files if field.startswith("turn_signal_")]
        if any(re.fullmatch(r"turn_signal_\d+", field) is None for field in fields):
          raise ValueError("Invalid sequential turn signal frame field.")

        for index, field in enumerate(sorted(fields, key=lambda key: int(key.rsplit("_", 1)[1])), 1):
          save_image(files[field], directory, f"turn_signal_{index:0{len(str(len(fields)))}d}", sequential=True)
      elif upload := files.get("turnSignal"):
        save_image(upload, directory, "turn_signal")

      if upload := files.get("turnSignalBlindspot"):
        save_image(upload, directory, "turn_signal_blindspot")

      if not any(path.suffix.lower() in IMAGE_FORMATS for path in directory.iterdir()):
        raise ValueError("Choose at least one turn signal image.")

    elif component == "sounds":
      for sound in SOUND_NAMES:
        if upload := files.get(sound):
          save_sound(upload, directory, sound)

      if not any((directory / f"{sound}.wav").is_file() for sound in SOUND_NAMES):
        raise ValueError("Choose at least one sound.")

    else:
      images = [(f"distanceIcons_{icon}", icon, (250, 250)) for icon in DISTANCE_ICONS]
      if component == "icons":
        images = [("homeButton", "button_home", (250, 250)), ("settingsButton", "button_settings", (169, 104))]

      for field, stem, dimensions in images:
        if upload := files.get(field):
          save_image(upload, directory, stem, dimensions)

      if not any(image_file(directory, stem) for _, stem, _ in images):
        raise ValueError("Choose at least one image for each selected component.")

    outputs.append((directory, live))

  return outputs


@contextmanager
def publish_theme(stage, outputs):
  previous = []
  published = []

  try:
    for staged, live in outputs:
      for parent in reversed(live.relative_to(THEME_SAVE_PATH).parents):
        real_directory(THEME_SAVE_PATH / parent)
      if live.is_symlink():
        raise ValueError("Existing theme assets cannot be symbolic links.")

      if live.exists():
        backup = stage / "previous" / live.relative_to(THEME_SAVE_PATH)
        backup.parent.mkdir(parents=True, exist_ok=True)
        live.rename(backup)
        previous.append((backup, live))

      if staged:
        staged.rename(live)
        published.append(live)

    yield
  except Exception:
    previous_paths = {live for _, live in previous}
    (stage / "rollback.json").write_text(json.dumps([str(live.relative_to(THEME_SAVE_PATH)) for live in published if live not in previous_paths]))

    for live in reversed(published):
      remove_path(live)
    for backup, live in reversed(previous):
      backup.rename(live)

    remove_path(stage / "previous")
    (stage / "rollback.json").unlink()
    raise
  else:
    remove_path(stage / "previous")


def recover_theme_updates():
  for stage in THEME_SAVE_PATH.glob(".theme_*_in_progress"):
    if stage.is_symlink() or not stage.is_dir():
      raise ValueError("Invalid unfinished theme update.")

    rolling_back = (stage / "rollback.json").is_file()
    if rolling_back:
      if (stage / "rollback.json").is_symlink():
        raise ValueError("Invalid unfinished theme update.")

      for relative in json.loads((stage / "rollback.json").read_text()):
        target = THEME_SAVE_PATH / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or not is_within(THEME_SAVE_PATH, target):
          raise ValueError("Invalid unfinished theme update path.")
        remove_path(target)

    # Existing releases used one pack backup; retain their interrupted-update recovery.
    legacy_name = next((path.name for path in (stage / "theme_packs").glob("*")), None)
    if legacy_name and (stage / "previous_theme").is_dir():
      live = THEME_SAVE_PATH / "theme_packs" / legacy_name
      if not os.path.lexists(live):
        (stage / "previous_theme").rename(live)

    backups = list((stage / "previous/theme_packs").glob("*/*"))
    backups.extend((stage / "previous/steering_wheels").glob("*"))
    for backup in backups:
      live = THEME_SAVE_PATH / backup.relative_to(stage / "previous")
      if rolling_back:
        remove_path(live)
      if not os.path.lexists(live):
        live.parent.mkdir(parents=True, exist_ok=True)
        backup.rename(live)

    for backup in (stage / "previous_wheels").glob("*"):
      live = THEME_SAVE_PATH / "steering_wheels" / backup.name
      if not os.path.lexists(live):
        live.parent.mkdir(parents=True, exist_ok=True)
        backup.rename(live)

    remove_path(stage)


def save_theme(form, files, applying=False):
  validated = validate_theme(form, files, applying)
  with state.theme_lock:
    real_directory(THEME_SAVE_PATH)
    recover_theme_updates()

    stage = Path(tempfile.mkdtemp(prefix=".theme_", suffix="_in_progress", dir=THEME_SAVE_PATH))
    try:
      outputs = prepare_theme(stage, validated, files, merge=True)
      with publish_theme(stage, outputs):
        if applying:
          selections = {COMPONENTS[component][1]: params.get(COMPONENTS[component][1]) for component in validated[1]}
          selections["PersonalizeOpenpilot"] = params.get("PersonalizeOpenpilot")

          try:
            for parameter in selections:
              if parameter == "PersonalizeOpenpilot":
                params.put_bool(parameter, True)
              else:
                params.put(parameter, POND_ACTIVE_THEME)

            params_memory.put_bool("UseActiveTheme", True)
            update_frogpilot_toggles()
          except Exception:
            for parameter, value in selections.items():
              if value is None:
                params.remove(parameter)
              else:
                params.put(parameter, value)
            raise

      params.remove("ThemesDownloaded")
    finally:
      # Keep backups if rollback itself fails; do not erase the last good assets.
      if not (stage / "previous").exists() and not (stage / "rollback.json").exists():
        remove_path(stage)


@blueprint.post("/api/themes")
def save_named_theme():
  save_theme(request.form, request.files)
  return {"message": f'Theme "{request.form["themeName"]}" saved!'}


@blueprint.post("/api/themes/apply")
def apply_theme():
  save_theme(request.form, request.files, applying=True)
  return {"message": "Theme applied successfully!"}


@blueprint.delete("/api/themes/delete/<path:theme>")
def delete_theme(theme):
  theme_type = request.args.get("type", "user")
  if theme_type == "holiday":
    abort(403, description="Holiday themes cannot be deleted.")

  with state.theme_lock:
    if params.get_bool("RandomThemes"):
      return {"error": "Disable Random Themes before deleting theme assets."}, 409

    if theme_type == "steering_wheel":
      root = THEME_SAVE_PATH / "steering_wheels"
      target = root / theme
      if target.resolve().parent != root.resolve() or target.stem == POND_ACTIVE_THEME:
        abort(403)

      selected = params.get("WheelIcon", encoding="utf-8") or ""
      if theme_asset_slug(selected) == theme_asset_slug(target.stem):
        return {"error": "Select a different steering wheel before deleting this one."}, 409
    else:
      target = theme_directory(theme, theme_type)
      if target.name == POND_ACTIVE_THEME:
        abort(403)

      component = request.args.get("component", "")
      folders = {folder: parameter for folder, parameter, _ in COMPONENTS.values() if folder != "steering_wheels"}
      if component and component not in folders:
        raise ValueError("Unknown theme component.")

      selected_folders = folders
      if component:
        selected_folders = {component: folders[component]}
      for parameter in selected_folders.values():
        selected = params.get(parameter, encoding="utf-8") or ""
        if theme_asset_slug(selected) == theme_asset_slug(theme):
          return {"error": "Select a different theme component before deleting this one."}, 409
      if component:
        target = target / component

    if not target.exists():
      abort(404, description="Theme component not found.")

    if theme_type == "steering_wheel":
      active = image_file(ACTIVE_THEME_PATH / "steering_wheel", "wheel")
      if active and active.resolve() == target.resolve():
        return {"error": "Select a different steering wheel before deleting the active one."}, 409
    elif any(is_within(target, ACTIVE_THEME_PATH / folder) for folder, _, _ in COMPONENTS.values() if folder != "steering_wheels"):
      return {"error": "Select a different theme component before deleting the active one."}, 409

    remove_path(target)
    params.remove("ThemesDownloaded")

  return {"message": "Theme component deleted."}


@blueprint.post("/api/themes/submit")
def submit_theme():
  username = (request.form.get("discordUsername") or "").strip()
  if not username:
    raise ValueError("Discord username is required for submission.")

  validated = validate_theme(request.form, request.files)
  with tempfile.TemporaryDirectory(prefix="pond_theme_submission_") as temporary:
    stage = Path(temporary)
    outputs = prepare_theme(stage, validated, request.files, merge=False)

    assets = []
    for staged, _ in outputs:
      if staged.is_dir():
        kind = staged.name
        archive = shutil.make_archive(str(stage / kind), "zip", staged)
        assets.append(ThemeAsset(kind, "application/zip", archive))
      else:
        content_type = {".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[staged.suffix]
        assets.append(ThemeAsset("steering_wheel", content_type, staged))

    with requests.Session() as session:
      current_app.extensions["frogpilot_api"].submit_theme_assets(request.form["themeName"].strip(), username, assets, session)

  return {"message": "Submission accepted for community review."}


@blueprint.post("/api/themes/download_asset")
def download_asset():
  data = request.get_json()
  if not isinstance(data, dict) or not isinstance(data.get("component"), str) or not isinstance(data.get("name"), str):
    raise ValueError("A component and name are required.")

  component = data["component"].strip()
  component = {"steering_wheel": "steering_wheels", "turn_signals": "signals"}.get(component, component)
  parameter = THEME_COMPONENT_PARAMS.get(component)
  slug = theme_asset_slug(data["name"].strip())
  if parameter is None or not is_safe_slug(slug):
    raise ValueError("Invalid theme component or name.")

  with state.theme_lock:
    if any(params_memory.get(key) for key in THEME_COMPONENT_PARAMS.values()):
      return {"error": "A theme download is already running."}, 409

    params_memory.remove(CANCEL_DOWNLOAD_PARAM)
    params_memory.put(DOWNLOAD_PROGRESS_PARAM, "Downloading...")
    params_memory.put(parameter, slug)

  return {"message": "Download started", "component": component, "param": parameter, "slug": slug}
