from openpilot.system.hardware import HARDWARE

def update_hardware_flag(flag_path, enabled):
  if not flag_path.is_file() and enabled:
    flag_path.touch()

    HARDWARE.reboot()
  elif flag_path.is_file() and not enabled:
    flag_path.unlink()

    HARDWARE.reboot()
