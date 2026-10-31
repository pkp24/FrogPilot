#!/usr/bin/env python3
import capnp
import hashlib
import requests
import secrets
import shutil
import time
import zstandard

from pathlib import Path

import cereal.messaging as messaging

from cereal import CEREAL_PATH, log
from openpilot.common.params import Params
from openpilot.system import sentry
from openpilot.system.loggerd.uploader import listdir_by_creation
from openpilot.system.loggerd.xattr_cache import getxattr, setxattr

from openpilot.frogpilot.common import frogpilot_api, frogpilot_paths, frogpilot_utilities, frogpilot_variables

COMPRESSION_LEVEL = 10

DRIVE_ATTR_NAME = "user.frogpilot_telemetry_drive"
LEGACY_UPLOAD_ATTR_VALUE = b"1"

SCHEMA_FILES = ("car.capnp", "custom.capnp", "include/c++.capnp", "legacy.capnp", "log.capnp")

EXCLUDED_MESSAGE_TYPES = frozenset((
  "accelerometer2",
  "androidLog",
  "boot",
  "clocks",
  "customReservedRawData0",
  "customReservedRawData1",
  "customReservedRawData2",
  "deviceState",
  "driverCameraState",
  "driverEncodeData",
  "driverEncodeIdx",
  "driverStateV2",
  "drivingModelData",
  "errorLogMessage",
  "frogpilotDeviceState",
  "gnssMeasurements",
  "gpsNMEA",
  "gyroscope2",
  "lightSensor",
  "livestreamDriverEncodeData",
  "livestreamDriverEncodeIdx",
  "livestreamRoadEncodeData",
  "livestreamRoadEncodeIdx",
  "livestreamWideRoadEncodeData",
  "livestreamWideRoadEncodeIdx",
  "logMessage",
  "magnetometer",
  "managerState",
  "mapRenderState",
  "microphone",
  "model",
  "navInstruction",
  "navModel",
  "navRoute",
  "navThumbnail",
  "peripheralState",
  "procLog",
  "qRoadEncodeData",
  "qRoadEncodeIdx",
  "qcomGnss",
  "roadEncodeData",
  "roadEncodeIdx",
  "temperatureSensor",
  "temperatureSensor2",
  "testJoystick",
  "thumbnail",
  "ubloxGnss",
  "ubloxRaw",
  "uiDebug",
  "uiPlan",
  "uploaderState",
  "wideRoadEncodeData",
  "wideRoadEncodeIdx",
))

REMOVED_FIELDS = {
  "carParams": ("carVin",),
  "liveLocationKalman": (
    "calibratedOrientationECEF",
    "filterState",
    "orientationECEF",
    "positionECEF",
    "positionGeodetic",
    "velocityECEF",
    "velocityNED",
  ),
  "livePose": ("filterState",),
}

REPLACEMENT_FIELDS = {
  "carControl": {"orientationNED.2": 0},
  "frogpilotPlan": {"gpsBearing": 0},
  "gpsLocation": {"altitude": 0, "bearingDeg": 0, "latitude": 0, "longitude": 0, "unixTimestampMillis": 0, "vNED": []},
  "gpsLocationExternal": {"altitude": 0, "bearingDeg": 0, "latitude": 0, "longitude": 0, "unixTimestampMillis": 0, "vNED": []},
  "liveLocationKalman": {
    "calibratedOrientationNED.value.2": 0,
    "gpsTimeOfWeek": 0,
    "gpsWeek": 0,
    "orientationNED.value.2": 0,
    "unixTimestampMillis": 0,
  },
  "livePose": {"orientationNED.z": 0},
  "modelV2": {"leads": [], "rawPredictions": b""},
  "roadCameraState": {"image": b""},
  "wideRoadCameraState": {"image": b""},
}

WHITELIST_FIELDS = {
  "driverMonitoringState": ("isRHD",),
  "initData": ("deviceType", "dirty", "gitCommit", "gitCommitDate", "osVersion", "version"),
}

def filter_log(data, schema):
  car_fingerprint = None

  fingerprinting = False

  filtered_data = bytearray()

  try:
    for event in schema.Event.read_multiple_bytes(data):
      try:
        which = event.which()
      except capnp.KjException:
        continue

      if which == "sentinel" and event.sentinel.type == "startOfRoute":
        fingerprinting = True
      elif which == "carParams":
        car_fingerprint = event.carParams.carFingerprint
        fingerprinting = False
      elif which == "carState":
        fingerprinting = False

      if which in EXCLUDED_MESSAGE_TYPES or which.endswith("DEPRECATED"):
        continue

      if which in ("can", "sendcan") and fingerprinting:
        continue

      builder = event.as_builder()

      if which in REMOVED_FIELDS:
        message = getattr(builder, which)

        for field in REMOVED_FIELDS[which]:
          message.disown(field)

      if which in REPLACEMENT_FIELDS:
        message = getattr(builder, which)

        for field, value in REPLACEMENT_FIELDS[which].items():
          target = message
          *parents, field = field.split(".")

          for parent in parents:
            target = getattr(target, parent)

          if field.isdigit():
            index = int(field)
            if index < len(target):
              target[index] = value
          elif hasattr(target, field):
            setattr(target, field, value)

      elif which in WHITELIST_FIELDS:
        kept = builder.init(which)
        source = getattr(event, which)

        for field in WHITELIST_FIELDS[which]:
          setattr(kept, field, getattr(source, field))

      filtered_data.extend(builder.to_bytes())
  except capnp.KjException:
    pass

  return filtered_data, car_fingerprint

class FrogPilotTelemetry:
  def __init__(self):
    self.params = Params()

    self.log_roots = frogpilot_utilities.get_log_roots()

    self.frogpilot_api = frogpilot_api.FrogPilotAPI(self.params)

    self.git_commit = self.params.get("GitCommit", encoding="utf-8")
    self.schemas = {self.git_commit: log}

    schema_path = frogpilot_paths.TELEMETRY_SCHEMAS_PATH / self.git_commit
    if not schema_path.is_dir():
      staging_path = frogpilot_paths.TELEMETRY_SCHEMAS_PATH / f".{self.git_commit}"
      for name in SCHEMA_FILES:
        (staging_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(CEREAL_PATH, name), staging_path / name)
      staging_path.rename(schema_path)

    self.compressor = zstandard.ZstdCompressor(level=COMPRESSION_LEVEL)

    self.session = requests.Session()

    self.sm = messaging.SubMaster(["deviceState"])

    self.route = self.params.get("CurrentRoute", encoding="utf-8")
    self.first_segment = None

    if self.route is not None:
      for log_root in self.log_roots:
        for lock_path in Path(log_root).glob(f"{self.route}--*/rlog.lock"):
          self.first_segment = int(lock_path.parent.name.rpartition("--")[2]) + 1

  def mark_shared_logs(self):
    if self.route is not None and self.first_segment is not None:
      for log_root in self.log_roots:
        for log_path in Path(log_root).glob(f"{self.route}--*/rlog"):
          if log_path.with_suffix(".lock").exists():
            continue

          if int(log_path.parent.name.rpartition("--")[2]) < self.first_segment:
            continue

          if getxattr(log_path, frogpilot_variables.UPLOAD_ATTR_NAME) is None:
            setxattr(log_path, frogpilot_variables.UPLOAD_ATTR_NAME, frogpilot_variables.UPLOAD_PENDING)

    route = self.params.get("CurrentRoute", encoding="utf-8")

    if route != self.route:
      self.route = route
      self.first_segment = 0

  def pending_logs(self):
    drive_ids = {}
    pending = []

    for log_root in self.log_roots:
      for segment in listdir_by_creation(log_root):
        log_path = Path(log_root, segment, "rlog")

        if not log_path.is_file():
          continue

        try:
          drive_id = getxattr(log_path, DRIVE_ATTR_NAME)
          uploaded = getxattr(log_path, frogpilot_variables.UPLOAD_ATTR_NAME)
        except OSError:
          continue

        route = segment.rpartition("--")[0]

        if uploaded == frogpilot_variables.UPLOAD_PENDING:
          if drive_id and drive_id != LEGACY_UPLOAD_ATTR_VALUE:
            drive_ids.setdefault(route, drive_id.decode())

          pending.append((log_path, route, drive_id))
        elif uploaded and uploaded != LEGACY_UPLOAD_ATTR_VALUE:
          drive_ids[route] = uploaded.decode()

    for log_path, route, existing_id in pending:
      if route not in drive_ids:
        drive_ids[route] = secrets.token_hex(16)

      drive_id = drive_ids[route].encode()

      if existing_id != drive_id:
        try:
          setxattr(log_path, DRIVE_ATTR_NAME, drive_id)
        except FileNotFoundError:
          continue

      if not log_path.with_suffix(".lock").is_file():
        yield log_path, drive_ids[route]

  def schema(self, git_commit):
    if git_commit not in self.schemas:
      schema_path = frogpilot_paths.TELEMETRY_SCHEMAS_PATH / git_commit / "log.capnp"
      self.schemas[git_commit] = capnp.SchemaParser().load(str(schema_path), imports=[str(schema_path.parent)])
    return self.schemas[git_commit]

  def upload(self, log_path, drive_id):
    data = log_path.read_bytes()

    try:
      git_commit = next(log.Event.read_multiple_bytes(data)).initData.gitCommit
      schema = self.schema(git_commit)
    except (OSError, StopIteration, capnp.KjException):
      return

    filtered_data, car_fingerprint = filter_log(data, schema)
    data = self.compressor.compress(filtered_data)

    submission = self.frogpilot_api.post_json("/v1/telemetry", {
      "car_fingerprint": car_fingerprint,
      "route_id": drive_id,
      "segment": int(log_path.parent.name.rpartition("--")[2]),
      "sha256": hashlib.sha256(data).hexdigest(),
      "size_bytes": len(data),
    }, self.session)

    if upload := submission.get("upload"):
      self.frogpilot_api.put_upload(upload, data, log_path.name, self.session)

  def can_upload(self):
    self.sm.update(0)

    if self.sm["deviceState"].started:
      return False

    return frogpilot_utilities.on_unmetered_network(self.sm["deviceState"])

  def update(self):
    self.mark_shared_logs()

    if not self.can_upload():
      return

    for log_path, drive_id in self.pending_logs():
      try:
        self.upload(log_path, drive_id)
        setxattr(log_path, frogpilot_variables.UPLOAD_ATTR_NAME, drive_id.encode())
      except (frogpilot_api.FrogPilotAPIError, requests.exceptions.RequestException):
        return
      except Exception as error:
        sentry.capture_exception(error, crash_log=False)

      if not self.can_upload():
        return

    for schema_path in frogpilot_paths.TELEMETRY_SCHEMAS_PATH.iterdir():
      if schema_path.name != self.git_commit:
        shutil.rmtree(schema_path)

    self.schemas = {self.git_commit: log}


def main():
  frogpilot_telemetry = FrogPilotTelemetry()

  while True:
    try:
      frogpilot_telemetry.update()
    except Exception as error:
      sentry.capture_exception(error, crash_log=False)

    time.sleep(60)


if __name__ == "__main__":
  main()
