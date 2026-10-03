import threading
import time

from openpilot.system.hardware import HARDWARE

from openpilot.frogpilot.common.frogpilot_utilities import run_cmd, running_threads
from openpilot.frogpilot.common.frogpilot_variables import params

def update_openpilot():
  def update_available():
    run_cmd(["pkill", "-SIGUSR1", "-f", "system.updated.updated"], "Checking for updates...", "Failed to check for update...", report=False)

    while params.get("UpdaterState", encoding="utf-8") != "checking...":
      time.sleep(1)

    while params.get("UpdaterState", encoding="utf-8") == "checking...":
      time.sleep(1)

    if not params.get_bool("UpdaterFetchAvailable"):
      return False

    while params.get_bool("IsOnroad") or running_threads.get("lock_doors", threading.Thread()).is_alive():
      time.sleep(60)

    run_cmd(["pkill", "-SIGHUP", "-f", "system.updated.updated"], "Update available, downloading...", "Failed to download update...", report=False)

    while not params.get_bool("UpdateAvailable"):
      time.sleep(60)

    return True

  if params.get("UpdaterState", encoding="utf-8") != "idle":
    return

  while params.get_bool("IsOnroad") or running_threads.get("lock_doors", threading.Thread()).is_alive():
    time.sleep(60)

  if not update_available():
    return

  while True:
    if not update_available():
      break

  HARDWARE.reboot()
