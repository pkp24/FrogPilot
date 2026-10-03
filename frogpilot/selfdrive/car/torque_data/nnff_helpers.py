import tomllib

from functools import cache
from pathlib import Path

from openpilot.selfdrive.car.interfaces import TORQUE_SUBSTITUTE_PATH

NNFF_MODELS_PATH = Path(__file__).parent / "nnff"

@cache
def get_nnff_model_files():
  return [file.stem for file in NNFF_MODELS_PATH.iterdir() if file.is_file()]

@cache
def get_nnff_substitutes():
  substitutes = {}
  with open(TORQUE_SUBSTITUTE_PATH, "rb") as f:
    substitutes_data = tomllib.load(f)
    substitutes = {key: value for key, value in substitutes_data.items()}
  return substitutes

def nnff_supported(car_fingerprint):
  from openpilot.frogpilot.selfdrive.controls.lib.neural_network_feedforward import get_nn_model_path
  return get_nn_model_path(car_fingerprint, "") is not None
