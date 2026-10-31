import os
import re
import subprocess
import time

from datetime import datetime
from flask import Blueprint, Response, abort, jsonify, send_file
from pathlib import Path
from werkzeug.utils import secure_filename

from openpilot.frogpilot.common import frogpilot_paths
from openpilot.frogpilot.system.the_pond.device import state
from openpilot.frogpilot.system.the_pond.helpers import is_within

blueprint = Blueprint("logs", __name__)

TMUX_LOG_EXTENSION = ".log"


def log_path(root, filename):
  path = Path(root) / filename
  if path.is_symlink() or not is_within(root, path) or not path.is_file():
    abort(404, "Log not found")
  return path


@blueprint.get("/api/error_logs")
def error_logs():
  if not frogpilot_paths.ERROR_LOGS_PATH.exists():
    return jsonify([])

  names = [path.name for path in frogpilot_paths.ERROR_LOGS_PATH.iterdir() if path.is_file() and not path.is_symlink()]
  return jsonify(sorted(name for name in names if name.startswith("error") or re.fullmatch(r"\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2}\.log", name)))


@blueprint.get("/api/error_logs/<filename>")
def read_error_log(filename):
  return send_file(log_path(frogpilot_paths.ERROR_LOGS_PATH, filename), mimetype="text/plain")


@blueprint.delete("/api/error_logs/<filename>")
def delete_error_log(filename):
  log_path(frogpilot_paths.ERROR_LOGS_PATH, filename).unlink()
  return {"message": "Error log deleted!"}


@blueprint.delete("/api/error_logs/delete_all")
def delete_error_logs():
  if frogpilot_paths.ERROR_LOGS_PATH.exists():
    for path in frogpilot_paths.ERROR_LOGS_PATH.iterdir():
      if path.is_file() and not path.is_symlink():
        path.unlink(missing_ok=True)

  return {"message": "All error logs deleted!"}


def tmux_log_files():
  paths = [*frogpilot_paths.TMUX_LOGS_PATH.glob(f"*{TMUX_LOG_EXTENSION}"), *frogpilot_paths.TMUX_LOGS_PATH.glob("*.json")]
  return [path for path in paths if path.is_file() and not path.is_symlink()]


def tmux_output(lines):
  try:
    return subprocess.check_output(["tmux", "capture-pane", "-p", "-J", "-S", lines], text=True, timeout=5)
  except (OSError, subprocess.SubprocessError):
    abort(409, "No active tmux session to capture")


@blueprint.post("/api/tmux_log/capture")
def capture_tmux():
  output = tmux_output("-")

  frogpilot_paths.TMUX_LOGS_PATH.mkdir(parents=True, exist_ok=True)
  with state.tmux_lock:
    filename = "tmux_log_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = frogpilot_paths.TMUX_LOGS_PATH / f"{filename}{TMUX_LOG_EXTENSION}"
    suffix = 1
    while path.exists():
      path = frogpilot_paths.TMUX_LOGS_PATH / f"{filename}_{suffix}{TMUX_LOG_EXTENSION}"
      suffix += 1

    with path.open("x", encoding="utf8") as output_file:
      output_file.write(output)

  return {"message": "Captured console log successfully!"}


@blueprint.get("/api/tmux_log/list")
def tmux_logs():
  if not frogpilot_paths.TMUX_LOGS_PATH.exists():
    return jsonify([])

  files = [{"filename": path.name, "timestamp": path.stat().st_mtime} for path in tmux_log_files()]
  return jsonify(sorted(files, key=lambda file: file["timestamp"], reverse=True))


@blueprint.get("/api/tmux_log/download/<filename>")
def download_tmux(filename):
  return send_file(log_path(frogpilot_paths.TMUX_LOGS_PATH, filename), mimetype="text/plain", as_attachment=True)


@blueprint.delete("/api/tmux_log/delete/<filename>")
def delete_tmux(filename):
  with state.tmux_lock:
    log_path(frogpilot_paths.TMUX_LOGS_PATH, filename).unlink()

  return {"message": "Tmux log deleted!"}


@blueprint.delete("/api/tmux_log/delete_all")
def delete_tmux_logs():
  with state.tmux_lock:
    if frogpilot_paths.TMUX_LOGS_PATH.exists():
      for path in tmux_log_files():
        path.unlink(missing_ok=True)

  return {"message": "All tmux logs deleted!"}


@blueprint.put("/api/tmux_log/rename/<old>/<new>")
def rename_tmux(old, new):
  new = secure_filename(new)
  if not new or not new.endswith(TMUX_LOG_EXTENSION):
    abort(400, "Invalid log filename")

  with state.tmux_lock:
    source = log_path(frogpilot_paths.TMUX_LOGS_PATH, old)
    target = frogpilot_paths.TMUX_LOGS_PATH / new
    if target.exists():
      abort(409, "A log with that name already exists")

    os.link(source, target)
    source.unlink()

  return {"message": "Log renamed!"}


@blueprint.get("/api/tmux_log/live")
def live_tmux():
  def generate():
    deadline = time.monotonic() + 3600
    previous = None

    while time.monotonic() < deadline:
      try:
        output = tmux_output("-1000")
      except Exception:
        yield "data: No active tmux session to stream.\n\n"
        return

      output = "\n".join(reversed(output.splitlines()))
      if output != previous:
        previous = output
        yield "data: " + output.replace("\n", "\ndata: ") + "\n\n"
      else:
        yield ": keepalive\n\n"

      time.sleep(1)

  return Response(generate(), mimetype="text/event-stream")
