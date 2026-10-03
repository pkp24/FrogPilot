import ipaddress
import re

from flask import abort, request
from pathlib import Path
from urllib.parse import urlsplit


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
  return isinstance(value, str) and re.fullmatch(r"[a-z0-9_'~.-]+", value) is not None and ".." not in value


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
