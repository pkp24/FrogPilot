import errno
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading

from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, Response, abort, request, send_file, stream_with_context
from werkzeug.utils import secure_filename

from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware.hw import Paths
from openpilot.system.loggerd.deleter import PRESERVE_ATTR_NAME, PRESERVE_ATTR_VALUE, PRESERVE_COUNT, PRESERVE_ROUTE_ATTR_NAME, has_preserve_attr

from openpilot.frogpilot.common.frogpilot_variables import SCREEN_RECORDINGS_PATH, VIDEO_CACHE_PATH, params
from openpilot.frogpilot.system.the_pond.device import logger_running
from openpilot.frogpilot.system.the_pond.helpers import is_within

blueprint = Blueprint("media", __name__)

CAMERAS = {"forward": "fcamera.hevc", "wide": "ecamera.hevc", "driver": "dcamera.hevc"}
FOOTAGE_PATHS = tuple(dict.fromkeys((Paths.log_root(HD=True, raw=True), Paths.log_root(konik=True, raw=True), Paths.log_root(raw=True))))
LOG_FILES = ("rlog", "rlog.bz2", "raw_log.bz2", "qlog", "qlog.bz2")
PROTECTED_SUFFIXES = (".hevc", ".ts", ".png", ".gif", ".lock")
SEGMENT_PATTERN = re.compile(r"([0-9a-fA-F]{8}--[0-9a-fA-F]{10})--(\d+)")

CACHE_MAX_BYTES = 2 * 1024 ** 3
CACHE_MIN_FREE = 500 * 1024 ** 2

MEDIA_TIMEOUT = 600
MEDIA_WAIT = 5

class MediaProcessor:
  def __init__(self):
    self.ffmpeg_slots = threading.BoundedSemaphore(2)
    self.ffprobe_slots = threading.BoundedSemaphore(2)

    self.output_locks = {}
    self.output_locks_mutex = threading.Lock()

    self.cache_mutex = threading.Lock()
    self.cache_reserved = 0
    self.duration_cache = {}

    self.nice = []
    if shutil.which("nice") and shutil.which("ionice"):
      self.nice = ["nice", "-n", "19", "ionice", "-c", "3"]

  @contextmanager
  def output_lock(self, path):
    with self.output_locks_mutex:
      lock, users = self.output_locks.get(path, (threading.Lock(), 0))
      self.output_locks[path] = (lock, users + 1)

    try:
      with lock:
        yield
    finally:
      with self.output_locks_mutex:
        lock, users = self.output_locks[path]
        if users == 1:
          del self.output_locks[path]
        else:
          self.output_locks[path] = (lock, users - 1)

  def run_ffmpeg(self, arguments):
    if not self.ffmpeg_slots.acquire(timeout=MEDIA_WAIT):
      abort(503, "Media processing is busy; try again shortly")
    try:
      subprocess.run([*self.nice, "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *arguments],
                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=MEDIA_TIMEOUT)
    finally:
      self.ffmpeg_slots.release()

  def video_duration(self, source, identity):
    with self.cache_mutex:
      if identity in self.duration_cache:
        return self.duration_cache[identity]

    if not self.ffprobe_slots.acquire(timeout=MEDIA_WAIT):
      abort(503, "Media processing is busy; try again shortly")
    try:
      result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", source_path(source)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=30)
      duration = float(result.stdout)
      if not math.isfinite(duration) or duration < 0:
        duration = 0
    except (ValueError, subprocess.SubprocessError):
      duration = 0
    finally:
      self.ffprobe_slots.release()

    with self.cache_mutex:
      if len(self.duration_cache) >= 512:
        self.duration_cache.pop(next(iter(self.duration_cache)))
      self.duration_cache[identity] = duration

    return duration

  def create_preview(self, source, output):
    scale = "scale='min(640,iw)':-1:flags=lanczos"
    if output.suffix.lower() == ".png":
      midpoint = self.video_duration(source, source_identity(source)) / 2
      options = ["-vf", scale, "-frames:v", "1", "-y", str(output)]
      self.run_ffmpeg(["-ss", str(midpoint), "-i", source_path(source), *options])
      if output.stat().st_size == 0:
        # Input seeking can skip the only keyframe in a short MPEG-TS segment.
        self.run_ffmpeg(["-i", source_path(source), "-ss", str(midpoint), *options])
    else:
      with tempfile.TemporaryDirectory() as directory:
        accelerated = Path(directory) / "accelerated.mp4"
        self.run_ffmpeg(["-i", source_path(source), "-an", "-vf", "setpts=PTS/35", str(accelerated)])
        filters = f"{scale},split[frames][colors];[colors]palettegen=stats_mode=single[palette];[frames][palette]paletteuse=new=1:dither=none"
        self.run_ffmpeg(["-i", str(accelerated), "-vf", filters, "-loop", "0", "-y", str(output)])

  def trim_cache(self, incoming_bytes=0, required_free=0):
    entries = [(path, path.stat()) for path in VIDEO_CACHE_PATH.glob("*.mp4")]
    entries.sort(key=lambda item: item[1].st_atime)
    size = sum(metadata.st_size for _, metadata in entries)
    allowance = CACHE_MAX_BYTES - min(incoming_bytes, CACHE_MAX_BYTES)

    for path, metadata in entries:
      if size <= allowance and shutil.disk_usage(VIDEO_CACHE_PATH).free >= CACHE_MIN_FREE + required_free:
        break
      path.unlink()
      size -= metadata.st_size

    if size > allowance or shutil.disk_usage(VIDEO_CACHE_PATH).free < CACHE_MIN_FREE + required_free:
      abort(503, "Not enough free storage to prepare this video")

  @contextmanager
  def reserve_cache(self, size):
    with self.cache_mutex:
      VIDEO_CACHE_PATH.mkdir(parents=True, exist_ok=True)
      self.trim_cache(size, self.cache_reserved + size)
      self.cache_reserved += size

    try:
      yield
    finally:
      with self.cache_mutex:
        self.cache_reserved -= size

  def convert_video(self, files):
    identities = [(str(path), source_identity(source)) for path, source in files]
    key = hashlib.sha256(json.dumps(identities).encode()).hexdigest()
    output = VIDEO_CACHE_PATH / f"{key}.mp4"

    with self.output_lock(output):
      with self.cache_mutex:
        if output.is_file():
          return open_source(output)

      size = sum(os.fstat(source.fileno()).st_size for _, source in files)
      with self.reserve_cache(size), tempfile.TemporaryDirectory(prefix=".video-", dir=VIDEO_CACHE_PATH) as temporary:
        temporary = Path(temporary)
        converted = temporary / "video.mp4"
        if len(files) == 1:
          inputs = ["-i", source_path(files[0][1])]
        else:
          listing = temporary / "segments.txt"
          listing.write_text("".join(f"file '{source_path(source)}'\n" for _, source in files))
          inputs = ["-f", "concat", "-safe", "0", "-i", str(listing)]

        try:
          tail = ["-movflags", "+faststart", "-y", str(converted)]
          try:
            self.run_ffmpeg([*inputs, "-c", "copy", *tail])
          except subprocess.CalledProcessError:
            self.run_ffmpeg([*inputs, "-c:v", "libx264", *tail])
        except subprocess.SubprocessError:
          cloudlog.exception("the_pond: video conversion failed")
          abort(503, "Could not prepare video")

        if converted.stat().st_size == 0:
          abort(503, "Video contains no playable footage")

        with self.cache_mutex:
          converted_size = converted.stat().st_size
          self.trim_cache(converted_size, self.cache_reserved - size)
          converted.replace(output)
          result = open_source(output)
          if converted_size > CACHE_MAX_BYTES:
            output.unlink()
          return result


processor = MediaProcessor()


@blueprint.errorhandler(OSError)
def storage_error(error):
  cloudlog.exception("the_pond: media storage operation failed")
  return {"error": "Could not complete the media storage operation"}, 500


@contextmanager
def storage_lock(path, exclusive=False):
  descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o664)
  try:
    operation = fcntl.LOCK_SH
    if exclusive:
      operation = fcntl.LOCK_EX

    try:
      fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
    except BlockingIOError:
      abort(423, "Recordings are busy; try again when recording or the current operation finishes")

    yield
  finally:
    os.close(descriptor)


@contextmanager
def recording_lock(exclusive=False):
  path = SCREEN_RECORDINGS_PATH.with_suffix(".lock")
  staging = Path(f"{SCREEN_RECORDINGS_PATH}.in_progress")
  if staging.is_symlink():
    abort(500, "Invalid screen-recording staging directory")

  staged = list(staging.glob("*.mp4.ready"))
  if staged:
    with storage_lock(path, True):
      for ready in staged:
        if not ready.is_file() or ready.is_symlink():
          continue

        destination = SCREEN_RECORDINGS_PATH / ready.name.removesuffix(".ready")
        candidate = destination
        suffix = 0
        while True:
          try:
            os.link(ready, candidate)
            break
          except FileExistsError:
            if os.path.samefile(ready, candidate):
              break
            suffix += 1
            candidate = destination.with_name(f"{destination.stem}-{suffix}.mp4")

        ready.unlink()

  with storage_lock(path, exclusive):
    yield


def media_file(root, filename, suffixes):
  path = root / filename
  if Path(filename).name != filename or path.suffix.lower() not in suffixes or path.is_symlink() or not is_within(root, path):
    abort(403, "Invalid media filename")
  return path


def open_source(path):
  descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
  if not stat.S_ISREG(os.fstat(descriptor).st_mode):
    os.close(descriptor)
    abort(404, "Media file not found")
  return os.fdopen(descriptor, "rb")


def source_identity(source):
  metadata = os.fstat(source.fileno())
  return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def source_path(source):
  return f"/proc/{os.getpid()}/fd/{source.fileno()}"


def send_media(source, filename, attachment=False):
  metadata = os.fstat(source.fileno())
  try:
    response = send_file(source, download_name=filename, as_attachment=attachment, conditional=False)
    response.content_length = metadata.st_size
    response.last_modified = metadata.st_mtime
    response.set_etag(f"{metadata.st_ino}-{metadata.st_mtime_ns}-{metadata.st_size}")
    return response.make_conditional(request.environ, accept_ranges=True, complete_length=metadata.st_size)
  except Exception:
    source.close()
    raise


def stream_list(key, items):
  def generate():
    yield f"data: {json.dumps({'progress': 0, 'total': len(items)})}\n\n"
    for processed, item in enumerate(items, 1):
      yield f"data: {json.dumps({key: [item]})}\n\ndata: {json.dumps({'progress': processed, 'total': len(items)})}\n\n"

  return Response(stream_with_context(generate()), mimetype="text/event-stream")


def recording_metadata(path, metadata=None):
  if metadata is None:
    metadata = path.stat()

  generated = False
  stem = path.stem
  try:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:_\d+)?", stem):
      if stem.isascii():
        datetime(*map(int, stem[:19].replace("_", "-").split("-")))
      else:
        datetime.strptime(re.sub(r"_\d+$", "", stem), "%Y-%m-%d_%H-%M-%S")
      generated = True
    elif re.fullmatch(r"[A-Za-z]+_\d{1,2}_\d{4}-\d{2}-\d{2}-\d{2}[AP]M(?:-\d+)?", stem):
      datetime.strptime(re.sub(r"-\d+$", "", stem), "%B_%d_%Y-%I-%M-%S%p")
      generated = True
  except ValueError:
    pass

  preview_url = f"/screen_recordings/{quote(stem)}"
  return {
    "filename": path.name,
    "gif": f"{preview_url}.gif",
    "png": f"{preview_url}.png",
    "timestamp": datetime.fromtimestamp(metadata.st_mtime).isoformat(),
    "is_custom_name": not generated,
  }


def preview_response(path, original, lock):
  with processor.output_lock(path):
    with lock():
      if not original.is_file():
        abort(404, "Recording not found")
      if path.is_file():
        try:
          version = os.getxattr(path, "user.the_pond_preview")
        except OSError as error:
          if error.errno != errno.ENODATA:
            raise
          version = None

        if version == b"2":
          return send_media(open_source(path), path.name)
      source = open_source(original)

    temporary = None
    try:
      with tempfile.NamedTemporaryFile(prefix=".preview-", suffix=path.suffix, dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
      processor.create_preview(source, temporary)
      if temporary.stat().st_size == 0:
        abort(503, "Could not create preview")

      with lock():
        if not original.is_file():
          abort(404, "Recording was removed")
        with open_source(original) as current:
          if source_identity(current) != source_identity(source):
            abort(409, "Recording changed; try again")

        os.setxattr(temporary, "user.the_pond_preview", b"2")
        temporary.replace(path)
        return send_media(open_source(path), path.name)
    except subprocess.SubprocessError:
      cloudlog.exception("the_pond: preview conversion failed")
      abort(503, "Could not create preview")
    finally:
      source.close()
      if temporary is not None:
        temporary.unlink(missing_ok=True)


@blueprint.get("/api/screen_recordings/list")
def list_recordings():
  with recording_lock():
    recordings = []
    for path in SCREEN_RECORDINGS_PATH.glob("*.mp4"):
      if path.is_file() and not path.is_symlink():
        recordings.append((path, path.stat()))

    recordings.sort(key=lambda item: item[1].st_mtime, reverse=True)
    metadata = [recording_metadata(path, information) for path, information in recordings]

  return stream_list("recordings", metadata)


@blueprint.get("/api/screen_recordings/download/<path:filename>")
def download_recording(filename):
  path = media_file(SCREEN_RECORDINGS_PATH, filename, (".mp4",))
  with recording_lock():
    if not path.is_file():
      abort(404, "Recording not found")
    return send_media(open_source(path), filename, attachment=True)


@blueprint.get("/screen_recordings/<path:filename>")
def recording_preview(filename):
  path = media_file(SCREEN_RECORDINGS_PATH, filename, (".png", ".gif"))
  original = media_file(SCREEN_RECORDINGS_PATH, path.with_suffix(".mp4").name, (".mp4",))
  return preview_response(path, original, recording_lock)


@blueprint.post("/api/screen_recordings/rename")
def rename_recording():
  data = request.get_json()
  if not isinstance(data, dict) or not isinstance(data.get("old"), str) or not isinstance(data.get("new"), str):
    abort(400, "Supply the original and new recording names")

  name = data["new"]
  if name.lower().endswith(".mp4"):
    name = name[:-4]
  name = secure_filename(name)
  if not name:
    abort(400, "Invalid recording name")

  original = media_file(SCREEN_RECORDINGS_PATH, data["old"], (".mp4",))
  renamed = media_file(SCREEN_RECORDINGS_PATH, f"{name}.mp4", (".mp4",))
  with recording_lock(True):
    if not original.is_file():
      abort(404, "Recording not found")
    if original == renamed:
      return {"message": "Renamed", "filename": renamed.name}

    files = [(original, renamed)]
    files.extend((original.with_suffix(extension), renamed.with_suffix(extension)) for extension in (".png", ".gif"))
    if any(os.path.lexists(target) for _, target in files):
      abort(400, "Target filename already exists")

    moved = []
    try:
      for source, target in files:
        if os.path.lexists(source):
          source.rename(target)
          moved.append((source, target))
    except OSError:
      for source, target in reversed(moved):
        target.rename(source)
      raise

  return {"message": "Renamed", "filename": renamed.name}


def remove_recording(path):
  for extension in (".png", ".gif"):
    path.with_suffix(extension).unlink(missing_ok=True)
  path.unlink()


@blueprint.delete("/api/screen_recordings/delete/<path:filename>")
def delete_recording(filename):
  path = media_file(SCREEN_RECORDINGS_PATH, filename, (".mp4",))
  with recording_lock(True):
    if not path.is_file():
      abort(404, "Recording not found")
    remove_recording(path)

  return {"message": "Deleted"}


@blueprint.delete("/api/screen_recordings/delete_all")
def delete_recordings():
  with recording_lock(True):
    for path in SCREEN_RECORDINGS_PATH.glob("*.mp4"):
      if path.is_file() and not path.is_symlink():
        remove_recording(path)

  return {"message": "All screen recordings deleted!"}


def route_lock(exclusive=False):
  return storage_lock(Path(FOOTAGE_PATHS[-1]).parent / ".route_mutation.lock", exclusive)


def route_library():
  routes = {}
  for root in FOOTAGE_PATHS:
    directory = Path(root)
    if not directory.is_dir():
      continue

    for segment in directory.iterdir():
      match = SEGMENT_PATTERN.fullmatch(segment.name)
      if match and segment.is_dir() and not segment.is_symlink():
        routes.setdefault(match[1], []).append(segment)

  for segments in routes.values():
    segments.sort(key=lambda segment: int(segment.name.rsplit("--", 1)[1]))

  return routes


def require_route(name, routes=None):
  if not isinstance(name, str) or SEGMENT_PATTERN.fullmatch(f"{name}--0") is None:
    abort(400, "Invalid route name")

  if routes is None:
    routes = route_library()
  if name not in routes:
    abort(404, "Route not found")

  return routes[name]


def route_busy(segments):
  if any(list(segment.glob("*.lock")) for segment in segments):
    return True
  if not logger_running():
    return False

  current_route = params.get("CurrentRoute", encoding="utf8")
  if current_route and any(segment.name.startswith(f"{current_route}--") for segment in segments):
    return True

  try:
    count = int(params.get("RouteCount", encoding="utf8"))
  except (TypeError, ValueError):
    return not current_route
  return any(segment.name.startswith(f"{(count - 1) & 0xffffffff:08x}--") for segment in segments)


def require_finished(segments):
  if route_busy(segments):
    abort(423, "Route is still being written")


def name_markers(segments):
  return [
    path for segment in segments for path in segment.iterdir()
    if path.name not in LOG_FILES and not path.name.endswith(PROTECTED_SUFFIXES)
    and path.is_file() and not path.is_symlink() and path.stat().st_size == 0
  ]


def route_date(segments):
  for segment in segments:
    for filename in LOG_FILES:
      path = segment / filename
      if path.is_file() and not path.is_symlink():
        return datetime.fromtimestamp(path.stat().st_ctime)

  return datetime.fromtimestamp(segments[0].stat().st_mtime)


def route_preservation(segments):
  if any(has_preserve_attr(segment, PRESERVE_ROUTE_ATTR_NAME) for segment in segments):
    return "route"
  if any(segment.name.endswith("--0") and has_preserve_attr(segment, PRESERVE_ATTR_NAME) for segment in segments):
    return "legacy"
  return None


def route_metadata(name, segments):
  markers = name_markers(segments)
  timestamp = route_date(segments).isoformat()
  if markers:
    timestamp = markers[0].name

  preview = segments[0]
  for segment in segments:
    if (segment / "qcamera.ts").is_file() or any((segment / camera).is_file() for camera in CAMERAS.values()):
      preview = segment
      break

  preservation = route_preservation(segments)
  return {
    "name": name,
    "gif": f"/thumbnails/{preview.name}/preview.gif",
    "png": f"/thumbnails/{preview.name}/preview.png",
    "timestamp": timestamp,
    "is_custom_name": bool(markers),
    "is_preserved": preservation is not None,
    "preservation": preservation,
  }


def selected_camera():
  camera = request.args.get("camera", "forward")
  if camera not in CAMERAS:
    abort(400, "Unknown camera")
  return camera


def camera_files(segments, camera):
  files = {}
  for segment in segments:
    path = segment / CAMERAS[camera]
    if path.is_file() and not path.is_symlink():
      files.setdefault(segment.name, path)

  return list(files.values())


@blueprint.get("/api/routes")
def list_routes():
  with route_lock():
    routes = route_library()
    metadata = []
    for name in sorted(routes, reverse=True):
      try:
        metadata.append(route_metadata(name, routes[name]))
      except FileNotFoundError:
        continue  # loggerd can reclaim completed footage during the scan.

  return stream_list("routes", metadata)


@blueprint.get("/api/routes/<name>")
def route_details(name):
  sources = []
  with ExitStack() as stack:
    with route_lock():
      segments = require_route(name)
      cameras = {camera: camera_files(segments, camera) for camera in CAMERAS}
      date = route_date(segments)
      if not route_busy(segments):
        for path in cameras["forward"]:
          duration_file = path.parent / "qcamera.ts"
          if not duration_file.is_file() or duration_file.is_symlink():
            duration_file = path
          sources.append(stack.enter_context(open_source(duration_file)))

    duration = sum(processor.video_duration(source, source_identity(source)) for source in sources)

  return {
    "name": name,
    "segment_urls": [f"/video/{segment}" for segment in dict.fromkeys(path.name for path in segments)],
    "total_duration": round(duration),
    "date": date,
    "available_cameras": [camera for camera, files in cameras.items() if files],
    "camera_segments": {camera: [f"/video/{path.parent.name}" for path in files] for camera, files in cameras.items() if files},
  }


@blueprint.post("/api/routes/<name>/preserve")
def preserve_route(name):
  with route_lock(True):
    routes = route_library()
    segments = require_route(name, routes)
    require_finished(segments)
    if route_preservation(segments) == "route":
      return {"message": "Route preserved!", "preservation": "route"}

    count = sum(route_preservation(route) == "route" for route in routes.values())
    if count >= PRESERVE_COUNT:
      abort(400, f"Maximum of {PRESERVE_COUNT} preserved routes reached")

    # Each storage root keeps its marker until critical-space cleanup removes the last segment.
    last_segments = {segment.parent: segment for segment in segments}
    marked = []
    try:
      for segment in last_segments.values():
        os.setxattr(segment, PRESERVE_ROUTE_ATTR_NAME, PRESERVE_ATTR_VALUE)
        marked.append(segment)
    except OSError:
      for segment in marked:
        os.removexattr(segment, PRESERVE_ROUTE_ATTR_NAME)
      raise

  return {"message": "Route preserved!", "preservation": "route"}


@blueprint.delete("/api/routes/<name>/preserve")
def unpreserve_route(name):
  with route_lock(True):
    segments = require_route(name)
    require_finished(segments)
    preservation = route_preservation(segments)

    for segment in segments:
      if has_preserve_attr(segment, PRESERVE_ROUTE_ATTR_NAME):
        os.removexattr(segment, PRESERVE_ROUTE_ATTR_NAME)
      if preservation != "route" and segment.name.endswith("--0") and has_preserve_attr(segment, PRESERVE_ATTR_NAME):
        os.removexattr(segment, PRESERVE_ATTR_NAME)

    preservation = route_preservation(segments)

  message = "Route unpreserved!"
  if preservation == "legacy":
    message = "Whole-route priority removed; the existing first-segment flag remains."
  return {"message": message, "preservation": preservation}


def delete_route_segments(segments):
  require_finished(segments)

  moved = []
  directories = {}
  try:
    for segment in segments:
      parent = segment.parent.parent
      if parent not in directories:
        directories[parent] = Path(tempfile.mkdtemp(prefix=".route-delete-", dir=parent))
      destination = directories[parent] / f"{len(moved)}-{segment.name}"
      segment.rename(destination)
      moved.append((segment, destination))
  except OSError:
    for original, destination in reversed(moved):
      destination.rename(original)
    for directory in directories.values():
      directory.rmdir()
    raise

  for directory in directories.values():
    shutil.rmtree(directory)


@blueprint.delete("/api/routes/<name>")
def delete_route(name):
  with route_lock(True):
    delete_route_segments(require_route(name))

  return {"message": "Route deleted!"}


@blueprint.delete("/api/routes/delete_all")
def delete_routes():
  data = {}
  if request.data:
    data = request.get_json()
  if not isinstance(data, dict) or set(data) - {"include_preserved"} or not isinstance(data.get("include_preserved", False), bool):
    abort(400, "include_preserved must be a boolean")

  with route_lock(True):
    routes = route_library()
    selected = []
    for segments in routes.values():
      if data.get("include_preserved", False) or route_preservation(segments) is None:
        selected.extend(segments)

    delete_route_segments(selected)

  return {"message": "Selected routes deleted!"}


@blueprint.post("/api/routes/rename")
def rename_route():
  data = request.get_json()
  if not isinstance(data, dict) or not isinstance(data.get("new"), str):
    abort(400, "Supply the original route and new name")

  name = secure_filename(data["new"])
  if not name or name in LOG_FILES or name.endswith(PROTECTED_SUFFIXES):
    abort(400, "Invalid route name")

  with route_lock(True):
    segments = require_route(data.get("old"))
    require_finished(segments)

    markers = name_markers(segments)
    targets = [segment / name for segment in segments]
    if any(os.path.lexists(target) and target not in markers for target in targets):
      abort(400, "The name conflicts with an existing route file")

    created = []
    removed = []
    try:
      for target in targets:
        if target not in markers:
          target.touch(exist_ok=False)
          created.append(target)
      for marker in markers:
        if marker not in targets:
          marker.unlink()
          removed.append(marker)
    except OSError:
      for marker in removed:
        marker.touch(exist_ok=False)
      for marker in created:
        marker.unlink()
      raise

  return {"message": "Route renamed successfully!", "timestamp": name}


@blueprint.post("/api/routes/clear_name")
def clear_route_name():
  data = request.get_json()
  if not isinstance(data, dict):
    abort(400, "Supply the route name")

  with route_lock(True):
    segments = require_route(data.get("name"))
    require_finished(segments)
    for marker in name_markers(segments):
      marker.unlink()

    timestamp = route_date(segments).isoformat()

  return {"message": "Route name cleared successfully!", "timestamp": timestamp}


@blueprint.get("/video/<name>/combined")
def combined_video(name):
  camera = selected_camera()
  with ExitStack() as stack:
    with route_lock():
      segments = require_route(name)
      require_finished(segments)
      paths = camera_files(segments, camera)
      if not paths:
        abort(404, "No footage is available for this camera")
      files = [(path, stack.enter_context(open_source(path))) for path in paths]

    converted = processor.convert_video(files)

  return send_media(converted, f"{name}-{camera}.mp4")


@blueprint.get("/video/<segment>")
def segment_video(segment):
  match = SEGMENT_PATTERN.fullmatch(segment)
  if not match:
    abort(404, "Video not found")

  camera = selected_camera()
  with ExitStack() as stack:
    with route_lock():
      segments = require_route(match[1])
      require_finished(segments)
      paths = camera_files([path for path in segments if path.name == segment], camera)
      if not paths:
        abort(404, "Video not found")
      source = stack.enter_context(open_source(paths[0]))

    converted = processor.convert_video([(paths[0], source)])

  return send_media(converted, f"{segment}-{camera}.mp4")


@blueprint.get("/thumbnails/<path:filename>")
def route_preview(filename):
  parts = Path(filename).parts
  if len(parts) != 2 or not SEGMENT_PATTERN.fullmatch(parts[0]) or parts[1] not in ("preview.png", "preview.gif"):
    abort(404, "Preview not found")

  route = parts[0].rsplit("--", 1)[0]
  selected = None
  with route_lock():
    segments = require_route(route)
    require_finished(segments)
    for segment in segments:
      if segment.name != parts[0]:
        continue
      for camera in ("qcamera.ts", *CAMERAS.values()):
        source = segment / camera
        if source.is_file() and not source.is_symlink():
          selected = segment / parts[1], source
          break
      if selected is not None:
        break

  if selected is None:
    abort(404, "Preview not found")

  return preview_response(*selected, route_lock)
