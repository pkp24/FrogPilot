import openpilot.system.sentry as sentry

from panda import Panda

from openpilot.frogpilot.common import frogpilot_variables

def flash_panda():
  serials = Panda.list()
  flashed = bool(serials)

  for serial in serials:
    try:
      with Panda(serial=serial) as panda:
        print(f"Flashing Panda {serial}")
        panda.flash(force=True)
    except Exception as exception:
      print(f"Failed to flash Panda {serial}: {exception}")
      sentry.capture_exception(exception)
      flashed = False

  if flashed:
    frogpilot_variables.params_memory.remove("FlashPanda")
  else:
    frogpilot_variables.params_memory.put_bool("FlashPanda", False)
