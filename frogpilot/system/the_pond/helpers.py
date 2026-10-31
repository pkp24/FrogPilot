import hashlib
import hmac
import ipaddress
import json
import re
import secrets

from datetime import datetime
from flask import abort, request
from pathlib import Path
from urllib.parse import urlsplit

from openpilot.frogpilot.common import frogpilot_variables

PAIRING_COOKIE = "the_pond"
PAIRING_COOKIE_AGE = 10 * 365 * 24 * 60 * 60


def json_body(fields=None, max_size=None):
  if max_size is not None and request.content_length is not None and request.content_length > max_size:
    abort(413, "Request is too large")

  data = request.get_json(silent=True)
  if not isinstance(data, dict):
    abort(400, "Expected a JSON object")
  if fields is not None and set(data) - fields:
    abort(400, "Unrecognized request fields")

  return data


def is_within(base, target):
  return Path(target).resolve().is_relative_to(Path(base).resolve())


def is_safe_display_name(name):
  return isinstance(name, str) and len(name) <= 256 and re.search(r"[<>\x00-\x1f\x7f]", name) is None


def is_safe_slug(value):
  return isinstance(value, str) and re.fullmatch(r"[a-z0-9_'.-]+(~[A-Za-z0-9_'.-]+)?", value) is not None and ".." not in value


def theme_asset_slug(name):
  return name.lower().replace("(", "").replace(")", "").replace(" ", "_").replace("_animated", "-animated")


def format_ordinal_date(date):
  day = date.day
  suffix = "th"
  if not 11 <= day <= 13:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

  return date.strftime(f"%B {day}{suffix}, %Y")


def http_origin(value):
  try:
    parsed = urlsplit(value or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
      return None
    if parsed.path or parsed.query or parsed.fragment:
      return None

    port = parsed.port
    if port is None:
      port = 80
      if parsed.scheme == "https":
        port = 443

    return parsed.scheme, parsed.hostname.lower().rstrip("."), port
  except ValueError:
    return None


def host_allowed(scheme, host):
  origin = http_origin(f"{scheme}://{host}")
  if origin is None:
    return False

  hostname = origin[1]
  if "." not in hostname:
    return True
  if hostname.endswith((".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain", ".fritz.box", ".ts.net")):
    return True

  try:
    ipaddress.ip_address(hostname)
    return True
  except ValueError:
    return False


def origin_allowed(origin, scheme, host, ports):
  expected = http_origin(f"{scheme}://{host}")
  return expected is not None and expected[2] in ports and http_origin(origin) == expected


def referer_allowed(referer, scheme, host, ports):
  try:
    parsed = urlsplit(referer or "")
    return origin_allowed(f"{parsed.scheme}://{parsed.netloc}", scheme, host, ports)
  except ValueError:
    return False


def is_paired():
  if not frogpilot_variables.params.get_bool("ThePondPairing"):
    return True

  token = request.cookies.get(PAIRING_COOKIE)
  authorization = request.headers.get("Authorization", "")
  if authorization.startswith("Bearer "):
    token = authorization.removeprefix("Bearer ")
  if token is None:
    return False

  browsers = json.loads(frogpilot_variables.params.get("ThePondPairedBrowsers") or b"[]")
  token_hash = hashlib.sha256(token.encode()).hexdigest()
  return any(hmac.compare_digest(browser["hash"], token_hash) for browser in browsers)


def pair_browser():
  token = secrets.token_urlsafe(32)

  browsers = json.loads(frogpilot_variables.params.get("ThePondPairedBrowsers") or b"[]")
  browsers.append({"hash": hashlib.sha256(token.encode()).hexdigest(), "id": secrets.token_hex(4),
                   "name": request.headers.get("User-Agent", "")[:200], "paired": int(datetime.now().timestamp())})
  frogpilot_variables.params.put("ThePondPairedBrowsers", json.dumps(browsers))

  return PAIRING_COOKIE, token, {"httponly": True, "max_age": PAIRING_COOKIE_AGE, "samesite": "Strict"}
