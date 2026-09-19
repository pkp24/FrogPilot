import openpilot.system.sentry as sentry

from panda import Panda

from openpilot.frogpilot.common.frogpilot_variables import params_memory

def flash_panda():
  for serial in Panda.list():
    try:
      with Panda(serial=serial) as panda:
        print(f"Flashing Panda {serial}")
        panda.flash(force=True)
    except Exception as exception:
      print(f"Failed to flash Panda {serial}: {exception}")
      sentry.capture_exception(exception)

  params_memory.remove("FlashPanda")
