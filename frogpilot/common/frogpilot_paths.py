from pathlib import Path

from openpilot.common.basedir import BASEDIR

ACTIVE_THEME_PATH = Path(__file__).parents[1] / "assets/active_theme"
HOLIDAY_THEMES_PATH = Path(__file__).parents[1] / "assets/holiday_themes"
RANDOM_EVENTS_PATH = Path(__file__).parents[1] / "assets/random_events"
STOCK_THEME_PATH = Path(__file__).parents[1] / "assets/stock_theme"
STOCK_THEME_COLORS_PATH = STOCK_THEME_PATH / "colors/colors.json"
THEME_COLORS_PATH = ACTIVE_THEME_PATH / "colors/colors.json"
THEME_SAVE_PATH = Path("/data/themes")
STEERING_WHEELS_PATH = THEME_SAVE_PATH / "steering_wheels"
THEME_PACKS_PATH = THEME_SAVE_PATH / "theme_packs"
FROG_THEME_PATH = THEME_PACKS_PATH / "frog"
THEME_SIZES_PATH = THEME_SAVE_PATH / "theme_sizes.json"

BACKUP_PATH = Path("/cache/on_backup")
FROGPILOT_BACKUPS = Path("/data/backups")
RESTORE_TEMP_PATH = Path("/data/restore_temp")
TOGGLE_BACKUPS = Path("/data/toggle_backups")

BOOT_LOGO_PATH = Path("/usr/comma/bg.jpg")
FROGPILOT_BOOT_LOGO_PATH = Path(__file__).parents[1] / "assets/other_images/frogpilot_boot_logo.png"
STOCK_BOOT_LOGO_PATH = Path(__file__).parents[1] / "assets/other_images/stock_bg.jpg"

BORDERS_PATH = Path(BASEDIR) / "frogpilot/assets/borders.json"
CITIES_PATH = Path(BASEDIR) / "frogpilot/assets/cities.json"

CLASSIC_MODEL_PATH = Path(BASEDIR) / "frogpilot/selfdrive/modeld/classic/models"

DEFAULT_THEME_COMPONENTS = {
  "colors": FROG_THEME_PATH / "colors",
  "distance_icons": THEME_PACKS_PATH / "frog-animated/distance_icons",
  "icons": THEME_PACKS_PATH / "frog-animated/icons",
  "signals": FROG_THEME_PATH / "signals",
  "sounds": FROG_THEME_PATH / "sounds",
}

ERROR_LOGS_PATH = Path("/data/error_logs")
ERROR_FILE_PATH = ERROR_LOGS_PATH / "error.txt"
SCREEN_RECORDINGS_PATH = Path("/data/media/screen_recordings")
VIDEO_CACHE_PATH = Path("/data/video_cache")

FROGS_GO_MOO_PATH = Path("/persist/frogsgomoo.py")

HD_LOGS_PATH = Path("/data/media/0/realdata_HD")
HD_PATH = Path("/cache/use_HD")

KONIK_LOGS_PATH = Path("/data/media/0/realdata_konik")
KONIK_PATH = Path("/cache/use_konik")

MAPS_PATH = Path("/data/media/0/osm/offline")

METADATA_SCRIPT = Path(BASEDIR) / "frogpilot/selfdrive/modeld/tinygrad/get_model_metadata.py"

METADATAS_PATH = Path(__file__).parents[1] / "selfdrive/modeld/model_metadata"
MODELS_PATH = Path("/data/models")
COMPILED_DIR = MODELS_PATH / "compiled"
MODEL_SIZES_PATH = MODELS_PATH / "model_sizes.json"
UNCOMPILED_DIR = MODELS_PATH / "uncompiled_downloads"
VERSION_PATH = MODELS_PATH / "model_version"

NAVIGATION_TRAINING_PATH = Path(__file__).parents[1] / "navigation/navigation_training"

NNFF_MODELS_PATH = Path(__file__).parents[1] / "assets/nnff_models"

NOT_VETTED_PATH = Path("/data/openpilot/not_vetted")

OFFLINE_MAPS_SCHEMA_PATH = Path(__file__).parents[1] / "system/offline_maps.capnp"

PARAMS_BACKUP_PATH = Path("/data/params_backup")

SECOC_KEY_PATH = Path("/cache/params/SecOCKey")

SPEED_LIMIT_FILLER_IMAGES_PATH = Path("/data/speed_limit_filler_images")
SPEED_LIMIT_FILLER_PATH = Path("/data/speed_limit_filler.json")
SPEED_LIMIT_FILLER_PENDING_IMAGES_PATH = SPEED_LIMIT_FILLER_IMAGES_PATH / "pending"

SPEED_LIMIT_READER_BUNDLED_PATH = Path(__file__).parents[1] / "assets/models"
SPEED_LIMIT_READER_MODEL_PATH = Path("/data/speed_limit_reader_model")
SPEED_LIMIT_READER_MANIFEST_PATH = SPEED_LIMIT_READER_MODEL_PATH / "manifest.json"

STOCK_MODEL_PATH = Path(BASEDIR) / "selfdrive/modeld/models"

TAILSCALE_PATH = Path("/data/tailscale")
TAILSCALE_SOCKET_PATH = TAILSCALE_PATH / "tailscaled.sock"
TAILSCALE_STATE_PATH = TAILSCALE_PATH / "state"
UNIT_PATH = Path("/etc/systemd/system/tailscaled.service")

TELEMETRY_SCHEMAS_PATH = Path("/data/telemetry_schemas")

TINYGRAD_MODELD_PATH = Path(BASEDIR) / "frogpilot/selfdrive/modeld/tinygrad"

TINYGRAD_REPO_PATH = Path(BASEDIR) / "tinygrad_repo"

TMUX_LOGS_PATH = Path("/data/tmux_logs")

TRACKING_PATH = Path("/cache/tracking")
