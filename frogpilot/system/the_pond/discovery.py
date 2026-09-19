import socket
import struct
import subprocess

from openpilot.common.swaglog import cloudlog

MDNS_GROUP = "224.0.0.251"
MDNS_HOSTNAME = "ThePond.local"
MDNS_PORT = 5353


def local_ip_for(address):
  with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    try:
      sock.connect((address, MDNS_PORT))
      return sock.getsockname()[0]
    except OSError:
      return None


def mdns_responder():
  name = b"".join(bytes([len(label)]) + label.encode("ascii") for label in MDNS_HOSTNAME.split(".")) + b"\0"
  header = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)
  record = name + struct.pack(">HHIH", 1, 0x8001, 120, 4)

  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      sock.bind(("", MDNS_PORT))
      sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(MDNS_GROUP) + socket.inet_aton("0.0.0.0"))

      while True:
        data, source = sock.recvfrom(2048)
        if len(data) < 12 or data[2] & 0x80 or name.lower() not in data[12:].lower():
          continue

        address = local_ip_for(source[0])
        if address is not None:
          if source[1] == MDNS_PORT:
            sock.sendto(header + record + socket.inet_aton(address), (MDNS_GROUP, MDNS_PORT))
          else:
            question = data[12:12 + len(name) + 4]
            if data[4:6] != b"\0\1" or len(question) != len(name) + 4 or question[:-4].lower() != name.lower():
              continue

            query_type, query_class = struct.unpack(">HH", question[-4:])
            if query_type not in (1, 255) or query_class & 0x7FFF not in (1, 255):
              continue

            response_header = data[:2] + struct.pack(">HHHHH", 0x8400, 1, 1, 0, 0)
            response_record = name + struct.pack(">HHIH", 1, 1, 10, 4)
            sock.sendto(response_header + question + response_record + socket.inet_aton(address), source)
  except OSError:
    cloudlog.exception("The Pond: local discovery stopped")


def redirect_port(port):
  rule = ["PREROUTING", "-p", "tcp", "--dport", "80", "-j", "REDIRECT", "--to-ports", str(port)]

  try:
    result = subprocess.run(["sudo", "iptables", "-t", "nat", "-C", *rule], capture_output=True, timeout=10)
    if result.returncode:
      subprocess.run(["sudo", "iptables", "-t", "nat", "-A", *rule], capture_output=True, check=True, timeout=10)

    cloudlog.info(f"The Pond: port 80 redirects to {port}")
  except (OSError, subprocess.SubprocessError):
    cloudlog.exception("The Pond: could not configure port 80")
