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

from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE

from openpilot.frogpilot.system.the_pond.device import is_driving, state

blueprint = Blueprint("tailscale", __name__)

TAILSCALE_PATH = Path("/data/tailscale")
UNIT_PATH = Path("/etc/systemd/system/tailscaled.service")


def service_unit():
  return f"""[Unit]
Description=Tailscale node agent
After=network.target

[Service]
ExecStart={TAILSCALE_PATH}/tailscaled \\
  --tun=userspace-networking \\
  --socks5-server=localhost:1055 \\
  --state={TAILSCALE_PATH}/state/tailscaled.state \\
  --socket={TAILSCALE_PATH}/tailscaled.sock \\
  --statedir={TAILSCALE_PATH}/state
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


def managed_installation():
  expected = service_unit()
  marker = TAILSCALE_PATH / ".the_pond_managed"

  try:
    if not (TAILSCALE_PATH / "tailscale").is_file() or not (TAILSCALE_PATH / "tailscaled").is_file():
      return False

    installed_lines = [line.strip() for line in UNIT_PATH.read_text().splitlines() if line.strip()]
    expected_lines = [line.strip() for line in expected.splitlines() if line.strip()]
    return installed_lines == expected_lines and (not marker.exists() or marker.read_text().strip() == hashlib.sha256(expected.encode()).hexdigest())
  except OSError:
    return False


def command(arguments):
  return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=60).stdout.strip()


@contextmanager
def writable_root():
  read_only = os.statvfs("/").f_flag & os.ST_RDONLY
  if read_only:
    command(["sudo", "mount", "-o", "remount,rw", "/"])

  try:
    yield
  finally:
    if read_only:
      command(["sudo", "mount", "-o", "remount,ro", "/"])


@contextmanager
def installation_operation():
  if not state.tailscale_lock.acquire(blocking=False):
    abort(409, "Another Tailscale operation is already running")

  try:
    yield
  finally:
    state.tailscale_lock.release()


def login_url():
  arguments = ["sudo", str(TAILSCALE_PATH / "tailscale"), "--socket", str(TAILSCALE_PATH / "tailscaled.sock")]
  arguments += ["up", "--hostname", f"{HARDWARE.get_device_type()}-the-pond"]
  process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)

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
          break

        output += chunk
        match = re.search(rb"https://login\.tailscale\.com/[^\s]+(?=\s)", output)
        if match:
          return match[0].decode("ascii")

    abort(504, "Tailscale did not return a sign-in URL. Please try again.")
  finally:
    try:
      if process.poll() is None:
        result = subprocess.run(["sudo", "kill", "-TERM", f"-{process.pid}"], capture_output=True, timeout=5)
        if result.returncode and process.poll() is None:
          raise RuntimeError("Could not stop Tailscale sign-in")

      try:
        process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        command(["sudo", "kill", "-KILL", f"-{process.pid}"])
        process.wait(timeout=5)
    finally:
      process.stdout.close()


@blueprint.get("/api/tailscale/installed")
def installation_status():
  managed = managed_installation()
  external = not managed and (UNIT_PATH.exists() or shutil.which("tailscale") is not None)
  return {"external": external, "installed": managed or external, "managed": managed}


@blueprint.post("/api/tailscale/setup")
def install():
  with installation_operation(), requests.Session() as session:
    if (UNIT_PATH.exists() or shutil.which("tailscale")) and not managed_installation():
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

      TAILSCALE_PATH.mkdir(parents=True, exist_ok=True)
      with TemporaryDirectory(prefix=".install-", dir=TAILSCALE_PATH) as temporary:
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
          (Path(temporary) / name).replace(TAILSCALE_PATH / name)
        (TAILSCALE_PATH / "state").mkdir(exist_ok=True)

        unit = service_unit()
        unit_file = TAILSCALE_PATH / "tailscaled.service"
        unit_file.write_text(unit)

        with writable_root():
          command(["sudo", "install", "-m", "644", str(unit_file), str(UNIT_PATH)])
          (TAILSCALE_PATH / ".the_pond_managed").write_text(hashlib.sha256(unit.encode()).hexdigest())

          command(["sudo", "systemctl", "daemon-reload"])
          command(["sudo", "systemctl", "enable", str(UNIT_PATH)])
          command(["sudo", "systemctl", "restart", "tailscaled"])

    return {"message": "Tailscale is ready for sign-in.", "auth_url": login_url()}


@blueprint.post("/api/tailscale/uninstall")
def uninstall():
  with installation_operation():
    if not managed_installation():
      abort(409, "Tailscale is managed outside The Pond")

    cloudlog.warning("The Pond: Tailscale uninstall requested")
    command(["sudo", "systemctl", "stop", "tailscaled"])

    with writable_root():
      command(["sudo", "systemctl", "disable", "tailscaled"])
      command(["sudo", "rm", "--", str(UNIT_PATH)])
    command(["sudo", "systemctl", "daemon-reload"])
    command(["sudo", "rm", "-rf", "--", str(TAILSCALE_PATH)])

    if UNIT_PATH.exists() or TAILSCALE_PATH.exists():
      abort(500, "Tailscale uninstall is incomplete")

  return {"message": "Tailscale uninstalled!"}
