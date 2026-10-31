import hashlib
import os
import re
import requests
import selectors
import shutil
import subprocess
import tarfile
import time

from contextlib import contextmanager
from flask import Blueprint, abort
from pathlib import Path
from tempfile import TemporaryDirectory

from cereal import messaging
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE

from openpilot.frogpilot.common import frogpilot_paths
from openpilot.frogpilot.system.the_pond.device import is_driving, state

blueprint = Blueprint("tailscale", __name__)


def managed_installation():
  installed = all((frogpilot_paths.TAILSCALE_PATH / name).is_file() for name in ("tailscale", "tailscaled"))
  return installed and not frogpilot_paths.UNIT_PATH.exists()


@contextmanager
def installation_operation():
  if not state.tailscale_lock.acquire(blocking=False):
    abort(409, "Another Tailscale operation is already running")

  try:
    yield
  finally:
    state.tailscale_lock.release()


def login_url():
  arguments = [str(frogpilot_paths.TAILSCALE_PATH / "tailscale"), "--socket", str(frogpilot_paths.TAILSCALE_SOCKET_PATH)]
  arguments += ["up", "--hostname", f"{HARDWARE.get_device_type()}-the-pond"]
  process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

  try:
    output = b""
    deadline = time.monotonic() + 60
    with selectors.DefaultSelector() as selector:
      selector.register(process.stdout, selectors.EVENT_READ)
      while time.monotonic() < deadline:
        if not selector.select(max(0, deadline - time.monotonic())):
          break

        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
          if process.wait(timeout=5) == 0:
            return None
          break

        output += chunk
        match = re.search(rb"https://login\.tailscale\.com/[^\s]+(?=\s)", output)
        if match:
          return match[0].decode("ascii")

    abort(504, "Tailscale did not return a sign-in URL. Please try again.")
  finally:
    try:
      if process.poll() is None:
        process.terminate()

      try:
        process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    finally:
      process.stdout.close()


@blueprint.get("/api/tailscale/installed")
def installation_status():
  managed = managed_installation()
  external = not managed and (frogpilot_paths.UNIT_PATH.exists() or shutil.which("tailscale") is not None)
  return {"external": external, "installed": managed or external}


@blueprint.post("/api/tailscale/setup")
def install():
  with installation_operation(), requests.Session() as session:
    if (frogpilot_paths.UNIT_PATH.exists() or shutil.which("tailscale")) and not managed_installation():
      abort(409, "Tailscale is managed outside The Pond")

    if not managed_installation():
      cloudlog.warning("The Pond: Tailscale installation requested")

      response = session.get("https://pkgs.tailscale.com/stable/", timeout=15)
      response.raise_for_status()

      versions = re.findall(r"tailscale_(\d+\.\d+\.\d+)_arm64\.tgz", response.text)
      if not versions:
        abort(502, "Could not find the current Tailscale download")

      version = max(versions, key=lambda value: tuple(map(int, value.split("."))))
      filename = f"tailscale_{version}_arm64"
      url = f"https://pkgs.tailscale.com/stable/{filename}.tgz"

      checksum_response = session.get(url + ".sha256", timeout=15)
      checksum_response.raise_for_status()
      checksum = checksum_response.text.strip().split()
      if not checksum or re.fullmatch(r"[0-9a-fA-F]{64}", checksum[0]) is None:
        abort(502, "Invalid Tailscale checksum")

      frogpilot_paths.TAILSCALE_PATH.mkdir(parents=True, exist_ok=True)
      with TemporaryDirectory(prefix=".install-", dir=frogpilot_paths.TAILSCALE_PATH) as temporary:
        archive_path = Path(temporary) / "tailscale.tgz"
        digest = hashlib.sha256()

        with session.get(url, stream=True, timeout=(15, 60)) as download:
          download.raise_for_status()
          with archive_path.open("wb") as archive_file:
            for chunk in download.iter_content(256 * 1024):
              archive_file.write(chunk)
              digest.update(chunk)

        if digest.hexdigest() != checksum[0].lower():
          abort(502, "Tailscale checksum mismatch")

        with tarfile.open(archive_path, "r:gz") as archive:
          for name in ("tailscale", "tailscaled"):
            member = archive.getmember(f"{filename}/{name}")
            if not member.isfile():
              abort(502, "Invalid Tailscale binary in archive")

            with archive.extractfile(member) as source, (Path(temporary) / name).open("wb") as target:
              shutil.copyfileobj(source, target)
            (Path(temporary) / name).chmod(0o755)

        if is_driving():
          abort(423, "Tailscale installation is unavailable while driving")

        for name in ("tailscale", "tailscaled"):
          (Path(temporary) / name).replace(frogpilot_paths.TAILSCALE_PATH / name)
        frogpilot_paths.TAILSCALE_STATE_PATH.mkdir(exist_ok=True)

      state.send_request("updateToggles")

      deadline = time.monotonic() + 30
      while not frogpilot_paths.TAILSCALE_SOCKET_PATH.exists():
        if time.monotonic() > deadline:
          abort(504, "Tailscale did not start. Please try again.")
        time.sleep(1)

    auth_url = login_url()
    if auth_url is None:
      return {"message": "Tailscale is already signed in."}

    return {"message": "Tailscale is ready for sign-in.", "auth_url": auth_url}


@blueprint.post("/api/tailscale/uninstall")
def uninstall():
  with installation_operation():
    if not managed_installation():
      abort(409, "Tailscale is managed outside The Pond")

    cloudlog.warning("The Pond: Tailscale uninstall requested")
    for name in ("tailscale", "tailscaled"):
      (frogpilot_paths.TAILSCALE_PATH / name).unlink()
    state.send_request("updateToggles")

    subscriber = messaging.SubMaster(["managerState"])
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
      subscriber.update(1000)
      if subscriber.updated["managerState"] and not any(process.name == "tailscaled" and process.running for process in subscriber["managerState"].processes):
        break

    shutil.rmtree(frogpilot_paths.TAILSCALE_PATH)

  return {"message": "Tailscale uninstalled!"}
