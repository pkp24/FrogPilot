import base64
import dataclasses
import fcntl
import hashlib
import json
import jwt
import os
import requests
import secrets
import threading
import time
import uuid

from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from openpilot.common.api import get_key_pair
from openpilot.common.time import system_time_valid
from openpilot.system.hardware import HARDWARE

API_VERSION = 1

FROGPILOT_API = "https://api.frogpilot.com"

MAX_ASSET_BYTES = 32 * 1024 * 1024
TUS_CHUNK_BYTES = 6 * 1024 * 1024

TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class FrogPilotAPIError(RuntimeError):
  pass


class ThemeSubmissionError(RuntimeError):
  pass


class ThemeAsset:
  def __init__(self, kind, content_type, path):
    self.content_type = content_type

    self.kind = kind

    self.path = Path(path)

    self.size_bytes = self.path.stat().st_size

    if not 1 <= self.size_bytes <= MAX_ASSET_BYTES:
      raise ThemeSubmissionError(f"Invalid {kind} asset size")

    with self.path.open("rb") as source:
      self.sha256 = hashlib.file_digest(source, "sha256").hexdigest()


class FrogPilotAPI:
  def __init__(self, params):
    self.params = params

    self._credential_thread_lock = threading.Lock()

  @contextmanager
  def credential_lock(self):
    with self._credential_thread_lock:
      lock_fd = os.open(f"{self.params.get_param_path()}.frogpilot_api.lock", os.O_CREAT | os.O_RDWR, 0o600)
      try:
        fcntl.lockf(lock_fd, fcntl.LOCK_EX)
        yield
      finally:
        os.close(lock_fd)

  def generate_token(self):
    return secrets.token_urlsafe(32)

  def get_token(self):
    return self.params.get("FrogPilotApiToken", encoding="utf-8")

  def regenerate_token(self, failed_token, session=requests):
    with self.credential_lock():
      current_token = self.get_token()

      if current_token and current_token != failed_token:
        return current_token

      for attempt in range(2):
        if not system_time_valid():
          return None

        api_token = self.generate_token()
        response = self.signed_post("/v1/token", {"api_token_hash": hashlib.sha256(api_token.encode()).hexdigest()}, session=session)

        if response is not None and 200 <= response.status_code < 300:
          if self.params.put("FrogPilotApiToken", api_token) == 0:
            return api_token
          break

        if response is None or response.status_code != 409 or attempt:
          break

        retry_time = int(time.time()) + 1
        time.sleep(1)
        if int(time.time()) < retry_time:
          break

      self.params.remove("FrogPilotRegistration")
      return None

  def register_device(self, build_metadata):
    def register_thread():
      profile = {
        "build_metadata": dataclasses.asdict(build_metadata),
        "device_type": HARDWARE.get_device_type(),
        "os_version": HARDWARE.get_os_version(),
        "profile_schema_version": API_VERSION,
      }

      save_failed = False
      while True:
        while not system_time_valid():
          time.sleep(1)

        with self.credential_lock():
          api_token = self.get_token()
          if api_token and not save_failed:
            payload = {**profile, "api_token_hash": hashlib.sha256(api_token.encode()).hexdigest()}
            digest = self.body_digest(payload)
            if self.params.get("FrogPilotDongleId", encoding="utf-8") and self.params.get("FrogPilotRegistration", encoding="utf-8") == digest:
              return

          api_token = self.generate_token()
          payload = {**profile, "api_token_hash": hashlib.sha256(api_token.encode()).hexdigest()}
          digest = self.body_digest(payload)

          response = self.signed_post("/v1/register", payload)
          if response is not None:
            if 200 <= response.status_code < 300:
              try:
                frogpilot_dongle_id = response.json()["frogpilot_dongle_id"]
                if not isinstance(frogpilot_dongle_id, str) or not frogpilot_dongle_id.strip():
                  raise ValueError("Invalid device ID")
              except (KeyError, TypeError, ValueError):
                break

              for key, value in (("FrogPilotApiToken", api_token), ("FrogPilotDongleId", frogpilot_dongle_id), ("FrogPilotRegistration", digest)):
                if self.params.put(key, value) != 0:
                  save_failed = True
                  break
              else:
                return
            elif response.status_code not in (408, 409, 429) and response.status_code < 500:
              break

        time.sleep(60)

    threading.Thread(target=register_thread, daemon=True).start()

  def _post(self, path, session=requests, timeout=10, **kwargs):
    try:
      return session.post(f"{FROGPILOT_API}{path}", timeout=timeout, allow_redirects=False, **kwargs)
    except requests.exceptions.RequestException:
      return None

  def post(self, path, headers=None, session=requests, **kwargs):
    def send(token):
      return self._post(path, session=session, headers={**(headers or {}), "Authorization": f"Bearer {token}"}, **kwargs)

    token = self.get_token()

    if token:
      response = send(token)

      if response is None or response.status_code != 401:
        return response

    token = self.regenerate_token(token, session=session)
    return send(token) if token else None

  def post_json(self, path, payload, session=requests, timeout=30):
    response = self.post(path, json=payload, timeout=timeout, session=session)

    if response is None:
      raise FrogPilotAPIError(f"POST {path} failed (no response)")

    if not 200 <= response.status_code < 300:
      raise FrogPilotAPIError(f"POST {path} failed ({response.status_code})")

    return response.json()

  def body_digest(self, payload):
    return hashlib.sha256(json.dumps({**payload, "public_key": get_key_pair()[2]}, separators=(",", ":"), sort_keys=True).encode()).hexdigest()

  def signed_post(self, path, payload, session=requests):
    algorithm, private_key, public_key = get_key_pair()
    if not private_key:
      return None

    body = json.dumps({**payload, "public_key": public_key}, separators=(",", ":"), sort_keys=True)
    body_sha256 = hashlib.sha256(body.encode()).hexdigest()
    now = int(time.time())
    signed_at = time.monotonic()
    for attempt in range(2):
      token = jwt.encode({
        "aud": "api.frogpilot.com",
        "auth_version": API_VERSION,
        "body_sha256": body_sha256,
        "exp": now + 2 * 60,
        "iat": now,
        "method": "POST",
        "path": path,
      }, private_key, algorithm=algorithm)

      response = self._post(path, session=session, timeout=20, data=body, headers={"Authorization": f"JWT {token}", "Content-Type": "application/json"})
      received_at = time.monotonic()
      if response is None or response.status_code != 403 or attempt:
        return response

      try:
        server_date = parsedate_to_datetime(response.headers.get("Date", ""))
        if server_date.tzinfo is None:
          return response
        server_time = server_date.timestamp()
      except (TypeError, ValueError, OverflowError):
        return response

      if abs(server_time - (now + received_at - signed_at)) <= 5:
        return response

      now = int(server_time + time.monotonic() - received_at)

  def put_upload(self, upload, data, description, session=requests):
    if not upload["url"].lower().startswith("https://"):
      raise FrogPilotAPIError(f"{description} upload URL is not https")

    response = session.put(upload["url"], data=data, headers=upload.get("headers"), timeout=60, allow_redirects=False)

    if not 200 <= response.status_code < 300:
      raise FrogPilotAPIError(f"{description} upload failed ({response.status_code})")

  def upload_url(self, value, base=None):
    if not isinstance(value, str) or not value:
      raise ThemeSubmissionError("Invalid upload URL")

    url = value
    if base:
      url = urljoin(base, value)

    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
      raise ThemeSubmissionError("Invalid upload URL")
    if base and parsed.hostname != urlparse(base).hostname:
      raise ThemeSubmissionError("Invalid resumable upload location")

    return url

  def upload_headers(self, value):
    if not isinstance(value, dict) or any(not isinstance(item, str) for item in value.values()):
      raise ThemeSubmissionError("Invalid upload headers")
    return value

  def upload_offset(self, response):
    try:
      return int(response.headers["Upload-Offset"])
    except (KeyError, TypeError, ValueError) as error:
      raise ThemeSubmissionError("Invalid resumable upload offset") from error

  def upload_resumable(self, asset, upload, session):
    url = self.upload_url(upload.get("url"))
    headers = {**self.upload_headers(upload.get("headers")), "Tus-Resumable": "1.0.0"}
    if upload.get("chunk_size_bytes") != TUS_CHUNK_BYTES:
      raise ThemeSubmissionError("Unsupported resumable upload chunk size")

    metadata = upload.get("metadata")
    if not isinstance(metadata, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()):
      raise ThemeSubmissionError("Invalid resumable upload metadata")

    encoded_metadata = ",".join(f"{key} {base64.b64encode(value.encode()).decode()}" for key, value in metadata.items())
    response = session.post(url, headers={
      **headers, "Upload-Length": str(asset.size_bytes), "Upload-Metadata": encoded_metadata, "x-upsert": "false",
    }, timeout=30, allow_redirects=False)
    if response.status_code != 201:
      raise ThemeSubmissionError(f"Could not start {asset.kind} upload ({response.status_code})")

    url = self.upload_url(response.headers.get("Location"), url)

    offset = 0
    failures = 0
    with asset.path.open("rb") as source:
      while offset < asset.size_bytes:
        source.seek(offset)
        chunk = source.read(min(TUS_CHUNK_BYTES, asset.size_bytes - offset))
        if not chunk:
          raise ThemeSubmissionError(f"{asset.kind} changed during upload")

        try:
          response = session.patch(url, data=chunk, headers={
            **headers, "Content-Type": "application/offset+octet-stream", "Upload-Offset": str(offset),
          }, timeout=60, allow_redirects=False)
        except requests.exceptions.RequestException:
          response = None

        if response is not None and response.status_code == 204:
          next_offset = self.upload_offset(response)
          if next_offset != offset + len(chunk):
            raise ThemeSubmissionError("Unexpected resumable upload offset")

          offset = next_offset
          failures = 0
          continue

        if response is not None and response.status_code not in TRANSIENT_STATUSES:
          raise ThemeSubmissionError(f"Could not upload {asset.kind} ({response.status_code})")

        failures += 1
        response = session.head(url, headers=headers, timeout=30, allow_redirects=False)
        if response.status_code not in (200, 204):
          raise ThemeSubmissionError(f"Could not resume {asset.kind} upload ({response.status_code})")

        next_offset = self.upload_offset(response)
        if not offset <= next_offset <= offset + len(chunk):
          raise ThemeSubmissionError("Unexpected resumable upload offset")
        if next_offset > offset:
          failures = 0
        elif failures >= 3:
          raise ThemeSubmissionError(f"Could not upload {asset.kind}")
        offset = next_offset

  def submit_theme_assets(self, theme_name, discord_username, assets, session=requests):
    assets = list(assets)
    asset_kinds = {asset.kind for asset in assets}
    if not assets or len(asset_kinds) != len(assets):
      raise ThemeSubmissionError("No valid theme assets")
    if sum(asset.size_bytes for asset in assets) > MAX_ASSET_BYTES:
      raise ThemeSubmissionError("Theme submission exceeds the 32 MiB limit")

    # Keep the existing stable identity serialization used by the submission API.
    manifest = [{
      "content_type": asset.content_type, "kind": asset.kind, "sha256": asset.sha256, "size_bytes": asset.size_bytes,
    } for asset in assets]
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{theme_name}\n{discord_username}\n{manifest}"))

    try:
      response = self.post_json("/v1/theme-submissions", {
        "assets": manifest, "client_submission_id": identity, "discord_username": discord_username,
        "schema_version": API_VERSION, "theme_name": theme_name,
      }, session)
      if not isinstance(response, dict) or not isinstance(response.get("submission_id"), str) or not isinstance(response.get("assets"), list):
        raise ThemeSubmissionError("Invalid theme submission response")

      submission_id = response["submission_id"]
      remote_assets = {}
      for remote in response["assets"]:
        if not isinstance(remote, dict) or not isinstance(remote.get("kind"), str) or not isinstance(remote.get("asset_id"), str):
          raise ThemeSubmissionError("Invalid theme asset response")

        kind = remote["kind"]
        if kind not in asset_kinds or kind in remote_assets:
          raise ThemeSubmissionError("Invalid theme asset response")
        remote_assets[kind] = remote

      if set(remote_assets) != asset_kinds:
        raise ThemeSubmissionError("Incomplete theme asset response")

      for asset in assets:
        upload = remote_assets[asset.kind].get("upload")
        if upload is None:
          continue
        if not isinstance(upload, dict):
          raise ThemeSubmissionError("Invalid theme upload response")

        if upload.get("protocol") == "signed-put":
          self.upload_headers(upload.get("headers"))
          with asset.path.open("rb") as source:
            self.put_upload(upload, source, asset.kind, session)
        elif upload.get("protocol") == "tus":
          self.upload_resumable(asset, upload, session)
        else:
          raise ThemeSubmissionError("Unsupported asset upload protocol")

      completion = self.post_json(f"/v1/theme-submissions/{submission_id}/complete", {
        "assets": [{"asset_id": remote_assets[asset.kind]["asset_id"], "sha256": asset.sha256, "size_bytes": asset.size_bytes} for asset in assets],
        "schema_version": API_VERSION,
      }, session, timeout=120)
      if not isinstance(completion, dict) or completion.get("accepted") is not True or completion.get("submission_id") != submission_id:
        raise ThemeSubmissionError("Theme submission was not accepted")

      return submission_id
    except (requests.exceptions.RequestException, FrogPilotAPIError) as error:
      raise ThemeSubmissionError("Theme submission failed. Please try again later.") from error
