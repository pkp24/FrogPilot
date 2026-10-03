from pathlib import Path

METADATAS_PATH = Path(__file__).parent / "model_metadata"
MODELS_PATH = Path("/data/models")

DEFAULT_MODEL = "dark-souls"
DEFAULT_MODEL_NAME = "Dark Souls (Default) 👀📡"
DEFAULT_MODEL_VERSION = "v9"

TINYGRAD_FILES = [
  ("driving_policy_metadata.pkl", "policy metadata"),
  ("driving_policy_tinygrad.pkl", "policy model"),
  ("driving_vision_metadata.pkl", "vision metadata"),
  ("driving_vision_tinygrad.pkl", "vision model"),
]
ALL_TINYGRAD_FILES = TINYGRAD_FILES[:]

def get_tinygrad_files(model_version):
  return TINYGRAD_FILES

def get_downloaded_models(models, model_version_lookup):
  return [
    model for model in models
    if (
      model_version_lookup.get(model, DEFAULT_MODEL_VERSION) in {"v1", "v2", "v3", "v4", "v5", "v6"}
      and (MODELS_PATH / f"{model}.thneed").is_file()
    ) or (
      model_version_lookup.get(model, DEFAULT_MODEL_VERSION) not in {"v1", "v2", "v3", "v4", "v5", "v6"}
      and all((MODELS_PATH / f"{model}_{filename}").is_file() for filename, _ in get_tinygrad_files(model_version_lookup.get(model, DEFAULT_MODEL_VERSION)))
    )
  ]

def clean_model_name(name):
  return (
    name.replace("🗺️", "")
    .replace("📡", "")
    .replace("👀", "")
    .replace("(Default)", "")
    .strip()
  )
