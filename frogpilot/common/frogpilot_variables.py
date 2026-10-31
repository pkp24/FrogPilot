#!/usr/bin/env python3
import json
import math
import time

from functools import lru_cache
from types import SimpleNamespace

from cereal import car, custom, log
from openpilot.common.conversions import Conversions as CV
from openpilot.common.params import Params
from openpilot.selfdrive.car import gen_empty_fingerprint
from openpilot.selfdrive.car.gm.values import CC_ONLY_CAR, GMFlags
from openpilot.selfdrive.car.hyundai.values import HyundaiFrogPilotFlags
from openpilot.selfdrive.car.interfaces import CarInterfaceBase
from openpilot.selfdrive.car.mock.interface import CarInterface as MockCarInterface
from openpilot.selfdrive.car.mock.values import CAR as MOCK
from openpilot.selfdrive.car.toyota.values import ToyotaFlags, ToyotaFrogPilotFlags
from openpilot.selfdrive.controls.lib.desire_helper import LANE_CHANGE_SPEED_MIN
from openpilot.selfdrive.controls.lib.drive_helpers import MAX_LATERAL_ACCEL_NO_ROLL
from openpilot.selfdrive.locationd import torqued
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.system.hardware.power_monitoring import VBATT_PAUSE_CHARGING
from openpilot.system.version import get_build_metadata
from panda import ALTERNATIVE_EXPERIENCE, Panda

from openpilot.frogpilot.common import frogpilot_paths, frogpilot_utilities

params = Params()
params_cache = Params("/cache/params")
params_default = Params("/dev/shm/params_default")
params_memory = Params("/dev/shm/params")

GearShifter = car.CarState.GearShifter
SafetyModel = car.CarParams.SafetyModel

CITY_SPEED_LIMIT = 25                     # m/s, ~56 mph; at or above this counts as highway driving
CRUISING_SPEED = 5                        # m/s, roughly the speed cars go when not touching the gas while in drive
CURVE_AHEAD_ENTER = 0.6                   # m/s^2, peak lateral acceleration on the planned path that counts as a curve ahead
CURVE_AHEAD_EXIT = 0.4                    # m/s^2, peak lateral acceleration on the planned path below which the curve ahead has ended
DEFAULT_LATERAL_ACCELERATION = 2.0        # m/s^2, typical lateral acceleration when taking curves
EARTH_RADIUS = 6378137                    # Radius of the Earth in meters
LATERAL_DELAY_OFFSET = 0.2                # Seconds added to the steering actuator delay to get the total lateral delay
LAT_SMOOTH_SECONDS = 0.1                  # Seconds of lateral smoothing for models that don't set their own
LEAD_DEPARTURE_SPEED = 1.0                # m/s, leads moving slower than this are treated as stopped
LEAD_STOP_MARGIN = 4                      # Meters past the planned stopping point where a lead still counts as relevant
MAPBOX_MONTHLY_REQUEST_LIMIT = 100_000    # Mapbox's free monthly request allowance
MAX_ACCELERATION = 4.0                    # ISO 15622:2018
MAX_T_FOLLOW = 3.0                        # Maximum allowed following duration. Larger values risk losing track of the lead but may be increased as models improve
MINIMUM_LATERAL_ACCELERATION = 1.3        # m/s^2, typical minimum lateral acceleration when taking curves
MINIMUM_PLANNED_SPEED = 2.0               # m/s, model path points predicted slower than this are stop approaches, not curves
PLANNER_TIME = ModelConstants.T_IDXS[-1]  # Length of time the model projects out for
SIGN_IMAGE_MARGIN = 0.5                   # Share of a sign's width and height added on each side when its image is saved for Speed Limit Filler
STOPPING_SPEED = 1.0                      # m/s, planned speeds below this count as the model coming to a stop
STOP_TIME = PLANNER_TIME - 2              # Seconds of the model's planned speed checked for an upcoming stop
TACO_LAG_TIME = 4                         # Seconds of driving taken off each turn's distance so TACO brakes early enough to reach the turn speed
THRESHOLD = 1 - 1 / math.e                # Requires the condition to be true for ~1 second

ACTION_DELAY_MODELS = {"cd210-model", "pop-model"}
BACKUP_EXCLUDED_KEYS = {"FrogPilotTelemetry", "FrogPilotTelemetryConfirmed", "GithubSshKeys", "GithubUsername"}
CAR_MAKE_NAMES = {"GMC": "GMC", "SEAT": "SEAT", "SKODA": "Škoda"}
CLASSIC_MODEL_VERSIONS = {"v1", "v2", "v3", "v4"}
CURRENT_SPEED_STOP_MODELS = {"cd210-model", "pop-model"}
LKAS_BUTTON_BRANDS = {"chrysler", "ford", "gm", "honda", "mazda", "nissan"}
MAP_GEARS_BRANDS = {"gm", "toyota"}
MIN_STABLE_DELAY_MODELS = {"cd210-model"}
SETTINGS_BACKUP_STOCK_KEYS = {"DisengageOnAccelerator", "ExperimentalMode", "LanguageSetting", "LongitudinalPersonality", "OpenpilotEnabledToggle"}
THNEED_MODEL_VERSIONS = CLASSIC_MODEL_VERSIONS | {"v5", "v6"}

DEFAULT_MODEL = "dark-souls"
DEFAULT_MODEL_NAME = "Dark Souls (Default) 👀📡"
DEFAULT_MODEL_VERSION = "v9"

MAP_MATCH_MAX_AGE_NS = 2_000_000_000

NON_DRIVING_GEARS = [GearShifter.neutral, GearShifter.park, GearShifter.reverse, GearShifter.unknown]

RANDOM_EVENT_END = custom.FrogPilotCarEvent.EventName.youveGotMail
RANDOM_EVENT_START = custom.FrogPilotCarEvent.EventName.accel30

DEVELOPMENT_BRANCH = "FrogPilot-Development"
PR_BRANCH = "MAKE-PRS-HERE"
RELEASE_BRANCH = "FrogPilot"
STAGING_BRANCH = "FrogPilot-Staging"
TESTING_BRANCH = "FrogPilot-Testing"
VETTING_BRANCH = "FrogPilot-Vetting"

REPORT_REPOSITORIES = ("frogai/frogpilot", "frogai/frogpilot-development", "frogai/openpilot")
RESOURCES_REPO = "FrogAi/FrogPilot-Resources"

POND_ACTIVE_THEME = "pond_active-user_created"

SCREEN_RECORDING_COMPANION_SUFFIXES = (".gif", ".png")

PRESERVE_ROUTE_ATTR_NAME = "user.preserve_route"

UPLOAD_ATTR_NAME = "user.frogpilot_telemetry"
UPLOAD_DONE = b"done"
UPLOAD_PENDING = b"pending"

WEATHER_API_URL = "https://api.openweathermap.org/data/4.0/onecall/current"

ACCELERATION_PROFILES = {
  "STANDARD": 0,
  "ECO": 1,
  "SPORT": 2,
  "SPORT_PLUS": 3
}

BUTTON_FUNCTIONS = {
  "NOTHING": 0,
  "PERSONALITY_PROFILE": 1,
  "FORCE_COAST": 2,
  "PAUSE_LATERAL": 3,
  "PAUSE_LONGITUDINAL": 4,
  "EXPERIMENTAL_MODE": 5,
  "TRAFFIC_MODE": 6
}

CE_STATUS = {
  "OFF": 0,                      # Off
  "USER_DISABLED": 1,            # "Experimental Mode" disabled by user
  "USER_OVERRIDDEN": 2,          # "Experimental Mode" enabled by user
  "CURVATURE": 3,                # Road curvature condition
  "LEAD": 4,                     # Slower lead vehicle condition
  "SIGNAL": 5,                   # Turn signal condition
  "SPEED": 6,                    # Speed condition
  "SPEED_LIMIT": 7,              # Speed limit controller condition
  "STOP_LIGHT": 8,               # Stop light or sign condition
  "NAVIGATION_INTERSECTION": 9,  # Approaching intersection condition
  "NAVIGATION_TURN": 10,         # Approaching turn condition
}

CURVE_SPEED_PROFILES = {
  "GENTLE": 0,
  "STANDARD": 1,
  "SPORT": 2,
  "AUTO": 3
}

DECELERATION_PROFILES = {
  "STANDARD": 0,
  "ECO": 1,
  "ECO_PLUS": 2
}

DEVELOPER_SIDEBAR_METRICS = {
  "NONE": 0,
  "ACCELERATION_CURRENT": 1,
  "ACCELERATION_MAX": 2,
  "AUTOTUNE_ACTUATOR_DELAY": 3,
  "AUTOTUNE_FRICTION": 4,
  "AUTOTUNE_LATERAL_ACCELERATION": 5,
  "AUTOTUNE_STEER_RATIO": 6,
  "AUTOTUNE_STIFFNESS_FACTOR": 7,
  "ENGAGEMENT_LATERAL": 8,
  "ENGAGEMENT_LONGITUDINAL": 9,
  "LATERAL_STEERING_ANGLE": 10,
  "LATERAL_TORQUE_USED": 11,
  "LONGITUDINAL_ACTUATOR_ACCELERATION": 12,
  "LONGITUDINAL_MPC_JERK_ACCELERATION": 13,
  "LONGITUDINAL_MPC_JERK_DANGER_ZONE": 14,
  "LONGITUDINAL_MPC_JERK_SPEED_CONTROL": 15
}

DOWNLOADABLE_PARAMS = {
  "colors": "DownloadableColors",
  "distance_icons": "DownloadableDistanceIcons",
  "icons": "DownloadableIcons",
  "signals": "DownloadableSignals",
  "sounds": "DownloadableSounds",
  "steering_wheels": "DownloadableWheels"
}

EMPTY_DEFAULT_FLOAT_KEYS = {
  "LongitudinalActuatorDelay",
  "LongitudinalActuatorDelayStock",
  "StartAccel",
  "StartAccelStock",
  "SteerDelay",
  "SteerDelayStock",
  "SteerFriction",
  "SteerFrictionStock",
  "SteerKP",
  "SteerKPStock",
  "SteerLatAccel",
  "SteerLatAccelStock",
  "SteerRatio",
  "SteerRatioStock",
  "StopAccel",
  "StopAccelStock",
  "StoppingDecelRate",
  "StoppingDecelRateStock",
  "VEgoStarting",
  "VEgoStartingStock",
  "VEgoStopping",
  "VEgoStoppingStock"
}

EXCLUDED_KEYS = {
  "AvailableModelNames",
  "AvailableModels",
  "CalibratedLateralAcceleration",
  "CalibrationProgress",
  "CarParamsPersistent",
  "CurvatureData",
  "DesiredCurvatureHeadModels",
  "ExperimentalLongitudinalEnabled",
  "FrogPilotStats",
  "KonikMinutes",
  "LastUpdateTime",
  "LiveDelay",
  "MaxLateralAcceleration",
  "ModelDrivesAndScores",
  "ModelLatSmoothSeconds",
  "ModelVersions",
  "openpilotMinutes",
  "RandomizedModel",
  "SecOCKey",
  "SecOCKeys",
  "ThePondPairing",
  "UpdaterAvailableBranches"
}

HOLIDAY_GREETINGS = {
  "april_fools": "Happy April Fool's Day! 🤡",
  "christmas_week": "Merry Christmas! 🎄",
  "cinco_de_mayo": "¡Feliz Cinco de Mayo! 🌮",
  "easter_week": "Happy Easter! 🐰",
  "fourth_of_july": "Happy Fourth of July! 🎆",
  "halloween_week": "Happy Halloween! 🎃",
  "may_the_fourth": "May the 4th be with you! 🚀",
  "new_years": "Happy New Year! 🎉",
  "st_patricks_day": "Happy St. Patrick's Day! 🍀",
  "stitch_day": "Happy Stitch Day! 💙",
  "thanksgiving_week": "Happy Thanksgiving! 🦃",
  "valentines_day": "Happy Valentine's Day! ❤️",
  "world_frog_day": "Happy World Frog Day! 🐸"
}

PRE_TOMB_RAIDER_MODELS = {
  "alabama",
  "certified-herbalist",
  "dragon-rider",
  "duck-amigo",
  "filet-o-fish",
  "kerrygold",
  "last-horizon",
  "liquid-crystal",
  "los-angeles",
  "national-public-radio",
  "north-america",
  "north-dakota",
  "notre-dame",
  "null-pointer",
  "postal-service",
  "recertified-herbalist",
  "vegan-filet-o-fish",
  "vegetarian-filet-o-fish",
  "wd-40"
}

RENAMED_KEYS = {
  "CustomColors": "ColorScheme",
  "CustomDistanceIcons": "DistanceIconPack",
  "CustomIcons": "IconPack",
  "CustomSignals": "SignalAnimation",
  "CustomSounds": "SoundPack",
  "PersonalizeOpenpilot": "CustomThemes"
}

SPEED_LIMIT_READER_COMPATIBILITY = 1
SPEED_LIMIT_READER_MODEL_FILES = ("speed_limit_reader.mnn",)

SPEED_LIMIT_SOURCES = {
  "CAMERA": "Camera",
  "DASHBOARD": "Dashboard",
  "MAPBOX": "Mapbox",
  "MAP_DATA": "Map Data",
  "NAVIGATION": "Navigation",
  "NONE": "None",
}

TINYGRAD_FILES = [
  ("driving_policy_metadata.pkl", "policy metadata"),
  ("driving_policy_tinygrad.pkl", "policy model"),
  ("driving_vision_metadata.pkl", "vision metadata"),
  ("driving_vision_tinygrad.pkl", "vision model"),
]

TUNING_LEVELS = {
  "MINIMAL": 0,
  "STANDARD": 1,
  "ADVANCED": 2,
  "DEVELOPER": 3
}

frogpilot_default_params: list[tuple[str, str | bytes, int, str]] = [
  ("AccelerationPath", "1", 2, "0"),
  ("AccelerationProfile", "2", 0, "0"),
  ("AdjacentLeadsUI", "1", 3, "0"),
  ("AdjacentPath", "0", 3, "0"),
  ("AdjacentPathMetrics", "0", 3, "0"),
  ("AdvancedCustomUI", "0", 2, "0"),
  ("AdvancedLateralTune", "0", 3, "0"),
  ("AdvancedLongitudinalTune", "0", 3, "0"),
  ("AggressiveFollow", "1.25", 2, "1.25"),
  ("AggressiveJerkAcceleration", "50", 3, "50"),
  ("AggressiveJerkDanger", "100", 3, "100"),
  ("AggressiveJerkDeceleration", "50", 3, "50"),
  ("AggressiveJerkSpeed", "50", 3, "50"),
  ("AggressiveJerkSpeedDecrease", "50", 3, "50"),
  ("AggressivePersonalityProfile", "1", 2, "0"),
  ("AlertVolumeControl", "0", 2, "0"),
  ("AlwaysOnDM", "0", 0, "0"),
  ("AlwaysOnLateral", "1", 0, "0"),
  ("AlwaysOnLateralLKAS", "1", 2, "0"),
  ("AlwaysOnLateralMain", "1", 2, "0"),
  ("AutomaticallyDownloadModels", "1", 1, "0"),
  ("AutomaticUpdates", "1", 0, "1"),
  ("AvailableModelNames", "", 1, ""),
  ("AvailableModels", "", 1, ""),
  ("BigMap", "0", 2, "0"),
  ("BlacklistedModels", "", 2, ""),
  ("BlindSpotMetrics", "1", 3, "0"),
  ("BlindSpotPath", "1", 1, "0"),
  ("BorderMetrics", "0", 3, "0"),
  ("CalibratedLateralAcceleration", str(DEFAULT_LATERAL_ACCELERATION), 2, str(DEFAULT_LATERAL_ACCELERATION)),
  ("CalibrationProgress", "0", 3, "0"),
  ("CameraView", "3", 2, "0"),
  ("CarMake", "", 0, ""),
  ("CarModel", "", 0, ""),
  ("CarModelName", "", 0, ""),
  ("CarParamsPersistent", "", 0, ""),
  ("CECurves", "0", 1, "0"),
  ("CECurvesLead", "0", 1, "0"),
  ("CELead", "0", 1, "0"),
  ("CENavigation", "1", 2, "0"),
  ("CENavigationIntersections", "0", 2, "0"),
  ("CENavigationLead", "1", 2, "0"),
  ("CENavigationTurns", "1", 2, "0"),
  ("CESignalLaneDetection", "0", 2, "0"),
  ("CESignalSpeed", "55", 2, "0"),
  ("CESlowerLead", "0", 1, "0"),
  ("CESpeed", "0", 1, "0"),
  ("CESpeedLead", "0", 1, "0"),
  ("CEStopLights", "1", 1, "0"),
  ("CEStoppedLead", "0", 1, "0"),
  ("ClusterOffset", "1.015", 2, "1.015"),
  ("ColorScheme", "frog", 0, "stock"),
  ("Compass", "0", 1, "0"),
  ("ConditionalExperimental", "1", 1, "0"),
  ("CurvatureData", "", 2, ""),
  ("CurveSpeedController", "1", 1, "0"),
  ("CurveSpeedProfile", "3", 2, "3"),
  ("CustomAlerts", "0", 0, "0"),
  ("CustomCruise", "1", 2, "1"),
  ("CustomCruiseLong", "5", 2, "5"),
  ("CustomPersonalities", "0", 2, "0"),
  ("CustomThemes", "1", 0, "0"),
  ("CustomUI", "1", 0, "0"),
  ("DecelerationProfile", "1", 2, "0"),
  ("DesiredCurvatureHeadModels", "", 2, ""),
  ("DeveloperMetrics", "1", 3, "0"),
  ("DeveloperSidebar", "1", 3, "0"),
  ("DeveloperSidebarMetric1", "1", 3, "0"),
  ("DeveloperSidebarMetric2", "2", 3, "0"),
  ("DeveloperSidebarMetric3", "3", 3, "0"),
  ("DeveloperSidebarMetric4", "4", 3, "0"),
  ("DeveloperSidebarMetric5", "5", 3, "0"),
  ("DeveloperSidebarMetric6", "6", 3, "0"),
  ("DeveloperSidebarMetric7", "7", 3, "0"),
  ("DeveloperUI", "0", 3, "0"),
  ("DeveloperWidgets", "1", 3, "0"),
  ("DeviceManagement", "1", 1, "0"),
  ("DeviceShutdown", "9", 1, "33"),
  ("DisableOnroadUploads", "0", 2, "0"),
  ("DisableOpenpilotLongitudinal", "0", 0, "0"),
  ("DiscordUsername", "", 0, ""),
  ("DisengageVolume", "101", 2, "101"),
  ("DistanceButtonControl", "1", 2, "1"),
  ("DistanceIconPack", "stock", 0, "stock"),
  ("DriverCamera", "0", 1, "0"),
  ("DynamicPathWidth", "0", 2, "0"),
  ("DynamicPedalsOnUI", "1", 1, "0"),
  ("EngageVolume", "101", 2, "101"),
  ("ExperimentalLongitudinalEnabled", "0", 0, "0"),
  ("ExperimentalModeConfirmed", "0", 0, "0"),
  ("Fahrenheit", "0", 3, "0"),
  ("FavoriteDestinations", "", 0, ""),
  ("ForceAutoTune", "0", 3, "0"),
  ("ForceAutoTuneOff", "0", 3, "0"),
  ("ForceFingerprint", "0", 2, "0"),
  ("ForceMPHDashboard", "0", 3, "0"),
  ("ForceStops", "0", 2, "0"),
  ("ForceTorqueController", "0", 3, "0"),
  ("FPSCounter", "1", 3, "0"),
  ("FrogPilotStats", "", 0, ""),
  ("FrogPilotTelemetry", "1", 0, "0"),
  ("FrogPilotTelemetryConfirmed", "0", 0, "0"),
  ("FrogsGoMoosTweak", "1", 2, "0"),
  ("FullMap", "0", 2, "0"),
  ("GithubSshKeys", "", 0, ""),
  ("GithubUsername", "", 0, ""),
  ("GoatScream", "0", 1, "0"),
  ("GreenLightAlert", "0", 0, "0"),
  ("GsmApn", "", 0, ""),
  ("GsmRoaming", "1", 0, "0"),
  ("HideAlerts", "0", 2, "0"),
  ("HideLeadMarker", "0", 2, "0"),
  ("HideMap", "0", 2, "0"),
  ("HideMapIcon", "0", 2, "0"),
  ("HideMaxSpeed", "0", 2, "0"),
  ("HideSpeed", "0", 2, "0"),
  ("HideSpeedLimit", "0", 2, "0"),
  ("HigherBitrate", "0", 2, "0"),
  ("HolidayThemes", "1", 0, "0"),
  ("HondaAltTune", "0", 2, "0"),
  ("HondaLowSpeedPedal", "0", 2, "0"),
  ("HondaMaxBrake", "0", 2, "0"),
  ("HumanAcceleration", "1", 2, "0"),
  ("HumanFollowing", "1", 2, "0"),
  ("HumanLaneChanges", "1", 2, "0"),
  ("IconPack", "frog-animated", 0, "stock"),
  ("IncreasedStoppedDistance", "0", 1, "0"),
  ("IncreasedStoppedDistanceLowVisibility", "0", 2, "0"),
  ("IncreasedStoppedDistanceRain", "0", 2, "0"),
  ("IncreasedStoppedDistanceRainStorm", "0", 2, "0"),
  ("IncreasedStoppedDistanceSnow", "0", 2, "0"),
  ("IncreaseFollowingLowVisibility", "0", 2, "0"),
  ("IncreaseFollowingRain", "0", 2, "0"),
  ("IncreaseFollowingRainStorm", "0", 2, "0"),
  ("IncreaseFollowingSnow", "0", 2, "0"),
  ("IncreaseThermalLimits", "0", 2, "0"),
  ("InstantReplay", "60", 1, "0"),
  ("IsLdwEnabled", "0", 0, "0"),
  ("IsMetric", "0", 0, "0"),
  ("KonikDongleId", "", 0, ""),
  ("KonikMinutes", "0", 0, "0"),
  ("LaneChanges", "1", 0, "1"),
  ("LaneChangeTime", "1.0", 1, "0"),
  ("LaneDetectionWidth", "0", 1, "0"),
  ("LaneLinesWidth", "4", 2, "2"),
  ("LateralTune", "1", 1, "0"),
  ("LeadDepartingAlert", "0", 0, "0"),
  ("LeadDetectionThreshold", "35", 3, "50"),
  ("LeadInfo", "1", 3, "0"),
  ("LiveDelay", "", 0, ""),
  ("LKASButtonControl", "5", 2, "0"),
  ("LockDoors", "1", 0, "0"),
  ("LockDoorsTimer", "0", 0, "0"),
  ("LongDistanceButtonControl", "5", 2, "0"),
  ("LongitudinalActuatorDelay", "", 3, ""),
  ("LongitudinalActuatorDelayStock", "", 3, ""),
  ("LongitudinalTune", "1", 0, "0"),
  ("LongPitch", "1", 2, "0"),
  ("LoudBlindspotAlert", "0", 0, "0"),
  ("LowVoltageShutdown", str(VBATT_PAUSE_CHARGING), 3, str(VBATT_PAUSE_CHARGING)),
  ("MapAcceleration", "0", 1, "0"),
  ("MapboxPublicKey", "", 0, ""),
  ("MapboxSecretKey", "", 0, ""),
  ("MapDeceleration", "0", 1, "0"),
  ("MapGears", "0", 2, "0"),
  ("MapsSelected", "", 0, ""),
  ("MapStyle", "1", 2, "0"),
  ("MaxDesiredAcceleration", "4.0", 3, "4.0"),
  ("MaxLateralAcceleration", "{}", 3, "{}"),
  ("MinimumLaneChangeSpeed", str(LANE_CHANGE_SPEED_MIN / CV.MPH_TO_MS), 2, str(LANE_CHANGE_SPEED_MIN / CV.MPH_TO_MS)),
  ("Model", DEFAULT_MODEL + "_default", 1, DEFAULT_MODEL + "_default"),
  ("ModelDrivesAndScores", "", 2, ""),
  ("ModelLatSmoothSeconds", "", 2, ""),
  ("ModelRandomizer", "0", 2, "0"),
  ("ModelUI", "1", 2, "0"),
  ("ModelVersions", "", 2, ""),
  ("NavigationUI", "1", 1, "0"),
  ("NavSettingLeftSide", "0", 0, "0"),
  ("NavSettingTime24h", "0", 0, "0"),
  ("NewLongAPI", "1", 3, "1"),
  ("NNFF", "1", 2, "0"),
  ("NNFFLite", "1", 2, "0"),
  ("NoLogging", "0", 2, "0"),
  ("NoUploads", "0", 2, "0"),
  ("NudgelessLaneChange", "0", 0, "0"),
  ("NumericalTemp", "1", 3, "0"),
  ("Offset1", "5", 0, "0"),
  ("Offset2", "5", 0, "0"),
  ("Offset3", "5", 0, "0"),
  ("Offset4", "5", 0, "0"),
  ("Offset5", "10", 0, "0"),
  ("Offset6", "10", 0, "0"),
  ("Offset7", "10", 0, "0"),
  ("OneLaneChange", "1", 2, "0"),
  ("OnroadDistanceButton", "0", 0, "0"),
  ("openpilotMinutes", "0", 0, "0"),
  ("PathEdgeWidth", "20", 2, "0"),
  ("PathWidth", "6.1", 2, "5.9"),
  ("PauseAOLOnBrake", "0", 1, "0"),
  ("PauseLateralOnSignal", "0", 1, "0"),
  ("PauseLateralSpeed", "0", 1, "0"),
  ("PedalsOnUI", "0", 1, "0"),
  ("PreferredSchedule", "2", 0, "0"),
  ("PromptDistractedVolume", "101", 2, "101"),
  ("PromptVolume", "101", 2, "101"),
  ("QOLLateral", "1", 1, "0"),
  ("QOLLongitudinal", "1", 1, "0"),
  ("QOLVisuals", "1", 0, "0"),
  ("RadarTracksUI", "0", 3, "0"),
  ("RainbowPath", "0", 1, "0"),
  ("RandomEvents", "0", 1, "0"),
  ("RandomizedModel", "", 2, ""),
  ("RandomThemes", "0", 1, "0"),
  ("RandomThemesHolidays", "0", 1, "0"),
  ("RecordFront", "0", 0, "0"),
  ("ReduceAccelerationLowVisibility", "0", 2, "0"),
  ("ReduceAccelerationRain", "0", 2, "0"),
  ("ReduceAccelerationRainStorm", "0", 2, "0"),
  ("ReduceAccelerationSnow", "0", 2, "0"),
  ("ReduceLateralAccelerationLowVisibility", "0", 2, "0"),
  ("ReduceLateralAccelerationRain", "0", 2, "0"),
  ("ReduceLateralAccelerationRainStorm", "0", 2, "0"),
  ("ReduceLateralAccelerationSnow", "0", 2, "0"),
  ("RefuseVolume", "101", 2, "101"),
  ("RelaxedFollow", "1.75", 2, "1.75"),
  ("RelaxedJerkAcceleration", "100", 3, "100"),
  ("RelaxedJerkDanger", "100", 3, "100"),
  ("RelaxedJerkDeceleration", "100", 3, "100"),
  ("RelaxedJerkSpeed", "100", 3, "100"),
  ("RelaxedJerkSpeedDecrease", "100", 3, "100"),
  ("RelaxedPersonalityProfile", "1", 2, "0"),
  ("ReverseCruise", "0", 1, "0"),
  ("RoadEdgesWidth", "2", 2, "2"),
  ("RoadNameUI", "1", 1, "0"),
  ("RotatingWheel", "1", 1, "0"),
  ("ScreenBrightness", "101", 2, "101"),
  ("ScreenBrightnessOnroad", "101", 2, "101"),
  ("ScreenManagement", "1", 1, "0"),
  ("ScreenRecorder", "1", 2, "0"),
  ("ScreenTimeout", "30", 2, "30"),
  ("ScreenTimeoutOnroad", "30", 2, "10"),
  ("SecOCKey", "", 0, ""),
  ("SecOCKeys", "", 0, ""),
  ("SetSpeedLimit", "0", 1, "0"),
  ("SetSpeedOffset", "0", 2, "0"),
  ("ShowCEMStatus", "1", 2, "0"),
  ("ShowCPU", "1", 3, "0"),
  ("ShowCSCStatus", "1", 2, "0"),
  ("ShowGPU", "0", 3, "0"),
  ("ShowIP", "0", 3, "0"),
  ("ShowMemoryUsage", "1", 3, "0"),
  ("ShownToggleDescriptions", "", 0, ""),
  ("ShowSLCOffset", "1", 0, "0"),
  ("ShowSpeedLimits", "1", 1, "0"),
  ("ShowSteering", "0", 3, "0"),
  ("ShowStoppingPoint", "1", 3, "0"),
  ("ShowStoppingPointMetrics", "1", 3, "0"),
  ("ShowStorageLeft", "0", 3, "0"),
  ("ShowStorageUsed", "0", 3, "0"),
  ("Sidebar", "0", 0, "0"),
  ("SignalAnimation", "frog", 0, "stock"),
  ("SignalMetrics", "0", 3, "0"),
  ("SLCConfirmation", "0", 0, "0"),
  ("SLCConfirmationHigher", "0", 0, "0"),
  ("SLCConfirmationLower", "0", 0, "0"),
  ("SLCFallback", "2", 1, "0"),
  ("SLCLookaheadHigher", "0", 2, "0"),
  ("SLCLookaheadLower", "0", 2, "0"),
  ("SLCMapboxFiller", "1", 1, "0"),
  ("SLCOverride", "1", 1, "0"),
  ("SLCPriority1", "Navigation", 2, "Navigation"),
  ("SLCPriority2", "Map Data", 2, "Map Data"),
  ("SLCPriority3", "Dashboard", 2, "Dashboard"),
  ("SNGHack", "1", 2, "0"),
  ("SoundPack", "frog", 0, "stock"),
  ("SpeedLimitChangedAlert", "0", 0, "0"),
  ("SpeedLimitController", "1", 0, "0"),
  ("SpeedLimitFiller", "1", 0, "0"),
  ("SpeedLimitSources", "0", 3, "0"),
  ("SshEnabled", "0", 0, "0"),
  ("StandardFollow", "1.45", 2, "1.45"),
  ("StandardJerkAcceleration", "100", 3, "100"),
  ("StandardJerkDanger", "100", 3, "100"),
  ("StandardJerkDeceleration", "100", 3, "100"),
  ("StandardJerkSpeed", "100", 3, "100"),
  ("StandardJerkSpeedDecrease", "100", 3, "100"),
  ("StandardPersonalityProfile", "1", 2, "0"),
  ("StandbyMode", "0", 1, "0"),
  ("StartAccel", "", 3, ""),
  ("StartAccelStock", "", 3, ""),
  ("StartupMessageBottom", "Human-tested, frog-approved 🐸", 0, "Always keep hands on wheel and eyes on road"),
  ("StartupMessageTop", "Hop in and buckle up!", 0, "Be ready to take over at any time"),
  ("StaticPedalsOnUI", "0", 1, "0"),
  ("SteerDelay", "", 3, ""),
  ("SteerDelayStock", "", 3, ""),
  ("SteerFriction", "", 3, ""),
  ("SteerFrictionStock", "", 3, ""),
  ("SteerKP", "", 3, ""),
  ("SteerKPStock", "", 3, ""),
  ("SteerLatAccel", "", 3, ""),
  ("SteerLatAccelStock", "", 3, ""),
  ("SteerRatio", "", 3, ""),
  ("SteerRatioStock", "", 3, ""),
  ("StopAccel", "", 3, ""),
  ("StopAccelStock", "", 3, ""),
  ("StoppedTimer", "0", 1, "0"),
  ("StoppingDecelRate", "", 3, ""),
  ("StoppingDecelRateStock", "", 3, ""),
  ("SubaruSNG", "1", 2, "0"),
  ("TacoTune", "0", 2, "0"),
  ("TacoTuneHacks", "0", 2, "0"),
  ("TetheringEnabled", "0", 0, "0"),
  ("ThemesDownloaded", "", 0, ""),
  ("ThePondPairing", "0", 0, "0"),
  ("ToyotaDoors", "1", 0, "0"),
  ("ToyotaDSUBypass", "0", 2, "0"),
  ("TuningLevel", "0", 0, "0"),
  ("TuningLevelConfirmed", "0", 0, "0"),
  ("TurnDesires", "0", 2, "0"),
  ("UnlockDoors", "1", 0, "0"),
  ("UpdaterAvailableBranches", "", 0, ""),
  ("UseKonikServer", "0", 2, "0"),
  ("UseSI", "1", 3, "1"),
  ("UseVienna", "0", 1, "0"),
  ("VEgoStarting", "", 3, ""),
  ("VEgoStartingStock", "", 3, ""),
  ("VEgoStopping", "", 3, ""),
  ("VEgoStoppingStock", "", 3, ""),
  ("VeryLongDistanceButtonControl", "6", 2, "0"),
  ("VoltSNG", "0", 2, "0"),
  ("WarningImmediateVolume", "101", 2, "101"),
  ("WarningSoftVolume", "101", 2, "101"),
  ("WeatherPresets", "0", 2, "0"),
  ("WeatherToken", "", 2, ""),
  ("WheelIcon", "frog", 0, "stock"),
  ("WheelSpeed", "0", 2, "0")
]

misc_tuning_levels: list[tuple[str, str | bytes, int, str]] = [
  ("ForceOnroad", "", 3, ""),
  ("ResetCurveData", "", 1, ""),
  ("SidebarMetrics", "1", 3, "0"),
  ("SLCPriority", "", 2, ""),
  ("WheelControls", "", 2, "")
]

default_values = {key: value for key, value, _, _ in frogpilot_default_params}
stock_values = {key: stock for key, _, _, stock in frogpilot_default_params}
tuning_levels = {key: level for key, _, level, _ in frogpilot_default_params + misc_tuning_levels}

def get_default_value(key):
  return default_values[key]

def get_stock_value(key):
  return stock_values[key]

def get_tuning_level(key):
  return tuning_levels[key]

def get_frogpilot_toggles(sm=None):
  if sm is None:
    process_frogpilot_toggles.cache_clear()
    return process_frogpilot_toggles(0)
  return process_frogpilot_toggles(sm["frogpilotPlan"].togglesUpdateTime)

@lru_cache(maxsize=1)
def process_frogpilot_toggles(update_time):
  toggles = params_memory.get("FrogPilotToggles")
  if toggles:
    return SimpleNamespace(**json.loads(toggles))
  return FrogPilotVariables().frogpilot_toggles

class FrogPilotVariables:
  def __init__(self):
    self.params = Params()

    self.frogpilot_toggles = SimpleNamespace()

    build_metadata = get_build_metadata()

    branch = build_metadata.channel
    self.development_branch = branch == DEVELOPMENT_BRANCH
    self.release_branch = branch == RELEASE_BRANCH
    self.vetting_branch = branch == VETTING_BRANCH

    remote = build_metadata.openpilot.git_origin.lower().removesuffix(".git")
    repository = "/".join(remote.replace(":", "/").split("/")[-2:])
    self.issue_report_available = repository in REPORT_REPOSITORIES and (not build_metadata.openpilot.is_dirty or frogpilot_paths.FROGS_GO_MOO_PATH.is_file())

    for k, v, _, _ in frogpilot_default_params:
      params_default.put(k, v)

    params_memory.put("FrogPilotTuningLevels", json.dumps(tuning_levels))

    self.stock_colors = json.loads(frogpilot_paths.STOCK_THEME_COLORS_PATH.read_text())

    self.update()

  def get_color(self, key, theme_colors):
    for source in (theme_colors, self.stock_colors):
      color = source.get(key)
      if isinstance(color, dict):
        return f"#{color.get('alpha', 255):02X}{color.get('red', 255):02X}{color.get('green', 255):02X}{color.get('blue', 255):02X}"
    return "#FFFFFFFF"

  def get_value(self, key, cast=bool, condition=True, conversion=None, default=None, minimum=None, maximum=None):
    if not condition or self.frogpilot_toggles.tuning_level < get_tuning_level(key):
      if default is not None:
        return default

      if cast is bool:
        return get_default_value(key) == "1" if condition else False

      if condition:
        value = get_default_value(key)
      else:
        value = get_stock_value(key)
    elif cast is bool:
      return self.params.get_bool(key)
    elif cast is float:
      value = self.params.get_float(key)
    elif cast is int:
      value = self.params.get_int(key)
    else:
      value = self.params.get(key, encoding="utf-8")

    if cast is not None:
      value = cast(value)

    if conversion is not None:
      value *= conversion

    if minimum is not None and value < minimum:
      value = minimum
    elif maximum is not None and value > maximum:
      value = maximum

    return value

  def get_button_function(self, key):
    function = self.get_value(key, cast=int)
    if function == BUTTON_FUNCTIONS["PAUSE_LATERAL"] or self.frogpilot_toggles.openpilot_longitudinal:
      return function
    return BUTTON_FUNCTIONS["NOTHING"]

  def torque_cache_matches(self, version):
    msg_bytes = self.params.get("CarParamsPrevRoute")
    if not msg_bytes:
      return False

    with car.CarParams.from_bytes(msg_bytes) as prev_CP, car.CarParams.from_bytes(self.params.get("CarParams")) as CP:
      return torqued.TorqueEstimator.get_restore_key(None, prev_CP, version) == torqued.TorqueEstimator.get_restore_key(None, CP, torqued.VERSION)

  def update(self, holiday_theme="stock", started=False):
    default = params_default
    level = tuning_levels
    toggle = self.frogpilot_toggles

    toggle.debug_mode = self.params.get_bool("DebugMode")
    toggle.force_offroad = params_memory.get_bool("ForceOffroad")
    toggle.force_onroad = params_memory.get_bool("ForceOnroad")
    toggle.issue_report_available = self.issue_report_available

    if self.params.get_bool("TuningLevelConfirmed"):
      toggle.tuning_level = self.params.get_int("TuningLevel")
    else:
      toggle.tuning_level = TUNING_LEVELS["ADVANCED"]

    toggle.is_metric = params.get_bool("IsMetric")
    distance_conversion = 1 if toggle.is_metric else CV.FOOT_TO_METER
    small_distance_conversion = 1 if toggle.is_metric else CV.INCH_TO_CM
    speed_conversion = CV.KPH_TO_MS if toggle.is_metric else CV.MPH_TO_MS

    msg_bytes = params.get("CarParams" if started else "CarParamsPersistent", block=started)
    if msg_bytes:
      with car.CarParams.from_bytes(msg_bytes) as cp_reader:
        CP = cp_reader.as_builder()
    else:
      CP = MockCarInterface.get_params(MOCK.MOCK, gen_empty_fingerprint(), [], False, toggle, False)
      MockCarInterface.configure_torque_tune(MOCK.MOCK, CP.lateralTuning)

      safety_config = car.CarParams.SafetyConfig.new_message()
      safety_config.safetyModel = car.CarParams.SafetyModel.noOutput
      CP.safetyConfigs = [safety_config]

    is_torque_car = CP.lateralTuning.which() == "torque"
    if not is_torque_car:
      CarInterfaceBase.configure_torque_tune(MOCK.MOCK, CP.lateralTuning)

    fpmsg_bytes = params.get("FrogPilotCarParams" if started else "FrogPilotCarParamsPersistent", block=started)
    if fpmsg_bytes:
      with custom.FrogPilotCarParams.from_bytes(fpmsg_bytes) as fpcp_reader:
        FPCP = fpcp_reader.as_builder()
    else:
      FPCP = MockCarInterface.get_frogpilot_params(MOCK.MOCK, gen_empty_fingerprint(), [], CP, toggle)

    selected_car_model = params.get("CarModel", encoding="utf-8")
    toggle.force_fingerprint = self.get_value("ForceFingerprint", condition=bool(selected_car_model))

    toggle.always_on_lateral_set = bool(CP.alternativeExperience & ALTERNATIVE_EXPERIENCE.ALWAYS_ON_LATERAL)
    toggle.car_make = CP.carName
    toggle.car_model = selected_car_model if toggle.force_fingerprint else CP.carFingerprint
    toggle.disable_openpilot_long = self.get_value("DisableOpenpilotLongitudinal")
    friction = CP.lateralTuning.torque.friction
    has_bsm = CP.enableBsm
    toggle.has_cc_long = toggle.car_make == "gm" and bool(CP.flags & GMFlags.CC_LONG.value)
    toggle.has_nnff = frogpilot_utilities.nnff_supported(toggle.car_model)
    has_pedal = CP.enableGasInterceptor
    toggle.has_radar = not CP.radarUnavailable
    toggle.has_sdsu = toggle.car_make == "toyota" and bool(CP.flags & ToyotaFlags.SMART_DSU.value)
    has_sng = CP.autoResumeSng
    toggle.has_zss = toggle.car_make == "toyota" and bool(FPCP.fpFlags & ToyotaFrogPilotFlags.ZSS.value)
    honda_nidec = CP.safetyConfigs[0].safetyModel == SafetyModel.hondaNidec
    hyundai_canfd = CP.safetyConfigs[-1].safetyModel == SafetyModel.hyundaiCanfd
    is_angle_car = CP.steerControlType == car.CarParams.SteerControlType.angle
    toggle.is_gm_cc_only = CP.carFingerprint in CC_ONLY_CAR
    latAccelFactor = CP.lateralTuning.torque.latAccelFactor
    longitudinalActuatorDelay = CP.longitudinalActuatorDelay
    toggle.openpilot_longitudinal = CP.openpilotLongitudinalControl and (honda_nidec or toggle.car_make == "gm" or not toggle.disable_openpilot_long)
    pcm_cruise = CP.pcmCruise
    startAccel = CP.startAccel
    steerActuatorDelay = CP.steerActuatorDelay
    steerKp = CP.lateralTuning.torque.kp
    steerRatio = CP.steerRatio
    stopAccel = CP.stopAccel
    toggle.stoppingDecelRate = CP.stoppingDecelRate
    toggle.lkas_allowed_for_aol = toggle.car_make == "hyundai" and (hyundai_canfd or bool(FPCP.fpFlags & HyundaiFrogPilotFlags.CAN_LFA_BTN.value))
    toggle.has_lkas_button = toggle.car_make in LKAS_BUTTON_BRANDS or toggle.lkas_allowed_for_aol or (toggle.car_make == "toyota" and bool(CP.flags & ToyotaFlags.TSS2.value))
    toggle.vEgoStarting = CP.vEgoStarting
    toggle.vEgoStopping = CP.vEgoStopping

    toggle.has_auto_tune = toggle.car_make in torqued.ALLOWED_CARS and is_torque_car

    msg_bytes = params.get("LiveTorqueParameters")
    if not started:
      self.drive_start_torque_cache = None
    elif self.drive_start_torque_cache is None:
      self.drive_start_torque_cache = msg_bytes or b""

    if msg_bytes:
      with log.Event.from_bytes(msg_bytes) as evt:
        live_lat_accel_factor = evt.liveTorqueParameters.latAccelFactorFiltered
        toggle.liveValid = evt.liveTorqueParameters.liveValid and (msg_bytes != self.drive_start_torque_cache or self.torque_cache_matches(evt.liveTorqueParameters.version))
    else:
      live_lat_accel_factor = 0.0
      toggle.liveValid = False

    learned_lateral_profile = json.loads(params.get("MaxLateralAcceleration") or "{}")
    learned_lateral_acceleration = learned_lateral_profile.get("value", 0.0) if learned_lateral_profile.get("car_fingerprint") == toggle.car_model else 0.0

    max_lateral_accel = CP.maxLateralAccel if CP.maxLateralAccel > 0 else DEFAULT_LATERAL_ACCELERATION
    if is_angle_car:
      max_lateral_accel = max(max_lateral_accel, learned_lateral_acceleration)
    elif is_torque_car and toggle.liveValid and latAccelFactor != 0:
      max_lateral_accel *= live_lat_accel_factor / latAccelFactor
    toggle.maxLateralAccel = min(max_lateral_accel, MAX_LATERAL_ACCEL_NO_ROLL)

    advanced_custom_ui = self.get_value("AdvancedCustomUI")
    toggle.hide_alerts = self.get_value("HideAlerts", condition=advanced_custom_ui and not toggle.debug_mode)
    toggle.hide_lead_marker = self.get_value("HideLeadMarker", condition=toggle.openpilot_longitudinal and advanced_custom_ui and not toggle.debug_mode)
    toggle.hide_map_icon = self.get_value("HideMapIcon", condition=advanced_custom_ui and not toggle.debug_mode)
    toggle.hide_map = self.get_value("HideMap", condition=toggle.hide_map_icon)
    toggle.hide_max_speed = self.get_value("HideMaxSpeed", condition=advanced_custom_ui and not toggle.debug_mode)
    toggle.hide_speed = self.get_value("HideSpeed", condition=advanced_custom_ui and not toggle.debug_mode)
    toggle.hide_speed_limit = self.get_value("HideSpeedLimit", condition=advanced_custom_ui and not toggle.debug_mode)
    toggle.use_wheel_speed = self.get_value("WheelSpeed", condition=advanced_custom_ui)

    advanced_lateral_tuning = self.get_value("AdvancedLateralTune")
    toggle.force_auto_tune = self.get_value("ForceAutoTune", condition=is_torque_car and not is_angle_car and not toggle.has_auto_tune and advanced_lateral_tuning)
    toggle.force_auto_tune_off = self.get_value("ForceAutoTuneOff", condition=is_torque_car and not is_angle_car and toggle.has_auto_tune and advanced_lateral_tuning)
    toggle.force_torque_controller = self.get_value("ForceTorqueController", condition=advanced_lateral_tuning)
    toggle.steerActuatorDelay = self.get_value("SteerDelay", cast=float, condition=advanced_lateral_tuning and self.params.get_float("SteerDelay") != 0, default=steerActuatorDelay, minimum=0.01, maximum=1.0)
    toggle.use_custom_steerActuatorDelay = bool(round(toggle.steerActuatorDelay, 2) != round(steerActuatorDelay, 2))
    toggle.friction = self.get_value("SteerFriction", cast=float, condition=advanced_lateral_tuning and self.params.get_float("SteerFriction") != 0, default=friction, minimum=0.01, maximum=1.0)
    toggle.use_custom_friction = (bool(round(toggle.friction, 2) != round(friction, 2)) and is_torque_car and not toggle.has_auto_tune and not toggle.force_auto_tune) or toggle.force_auto_tune_off
    toggle.steerKp = [[0], [self.get_value("SteerKP", cast=float, condition=is_torque_car and not is_angle_car and advanced_lateral_tuning and self.params.get_float("SteerKP") != 0, default=steerKp, minimum=steerKp * 0.5, maximum=steerKp * 1.5)]]
    toggle.latAccelFactor = self.get_value("SteerLatAccel", cast=float, condition=advanced_lateral_tuning and self.params.get_float("SteerLatAccel") != 0, default=latAccelFactor, minimum=latAccelFactor * 0.5, maximum=latAccelFactor * 1.5)
    toggle.use_custom_latAccelFactor = (bool(round(toggle.latAccelFactor, 2) != round(latAccelFactor, 2)) and is_torque_car and not toggle.has_auto_tune and not toggle.force_auto_tune) or toggle.force_auto_tune_off
    toggle.steerRatio = self.get_value("SteerRatio", cast=float, condition=advanced_lateral_tuning and self.params.get_float("SteerRatio") != 0, default=steerRatio, minimum=steerRatio * 0.5, maximum=steerRatio * 1.5)
    toggle.use_custom_steerRatio = (bool(round(toggle.steerRatio, 2) != round(steerRatio, 2)) and not toggle.force_auto_tune) or toggle.force_auto_tune_off

    advanced_longitudinal_tuning = toggle.openpilot_longitudinal and self.get_value("AdvancedLongitudinalTune")
    toggle.longitudinalActuatorDelay = self.get_value("LongitudinalActuatorDelay", cast=float, condition=advanced_longitudinal_tuning and (self.params.get_float("LongitudinalActuatorDelay") != 0 or self.params.get_float("LongitudinalActuatorDelayStock") != 0), default=longitudinalActuatorDelay, minimum=0, maximum=1)
    toggle.max_desired_acceleration = self.get_value("MaxDesiredAcceleration", cast=float, condition=advanced_longitudinal_tuning, minimum=0.1, maximum=MAX_ACCELERATION)
    toggle.startAccel = self.get_value("StartAccel", cast=float, condition=advanced_longitudinal_tuning and (self.params.get_float("StartAccel") != 0 or self.params.get_float("StartAccelStock") != 0), default=startAccel, minimum=0, maximum=MAX_ACCELERATION)
    toggle.stopAccel = self.get_value("StopAccel", cast=float, condition=advanced_longitudinal_tuning and (self.params.get_float("StopAccel") != 0 or self.params.get_float("StopAccelStock") != 0), default=stopAccel, minimum=-MAX_ACCELERATION, maximum=0)
    toggle.stoppingDecelRate = self.get_value("StoppingDecelRate", cast=float, condition=advanced_longitudinal_tuning and self.params.get_float("StoppingDecelRate") != 0, default=toggle.stoppingDecelRate, minimum=0.001, maximum=12)
    toggle.vEgoStarting = self.get_value("VEgoStarting", cast=float, condition=advanced_longitudinal_tuning and self.params.get_float("VEgoStarting") != 0, default=toggle.vEgoStarting, minimum=0.01, maximum=1)
    toggle.vEgoStopping = self.get_value("VEgoStopping", cast=float, condition=advanced_longitudinal_tuning and self.params.get_float("VEgoStopping") != 0, default=toggle.vEgoStopping, minimum=0.01, maximum=1)

    toggle.alert_volume_controller = self.get_value("AlertVolumeControl")
    toggle.disengage_volume = self.get_value("DisengageVolume", cast=float, condition=toggle.alert_volume_controller)
    toggle.engage_volume = self.get_value("EngageVolume", cast=float, condition=toggle.alert_volume_controller)
    toggle.prompt_volume = self.get_value("PromptVolume", cast=float, condition=toggle.alert_volume_controller, minimum=25)
    toggle.prompt_distracted_volume = self.get_value("PromptDistractedVolume", cast=float, condition=toggle.alert_volume_controller, minimum=25)
    toggle.refuse_volume = self.get_value("RefuseVolume", cast=float, condition=toggle.alert_volume_controller)
    toggle.warning_soft_volume = self.get_value("WarningSoftVolume", cast=float, condition=toggle.alert_volume_controller, minimum=25)
    toggle.warning_immediate_volume = self.get_value("WarningImmediateVolume", cast=float, condition=toggle.alert_volume_controller, minimum=25)

    prohibited_main_aol = not toggle.openpilot_longitudinal and toggle.lkas_allowed_for_aol
    toggle.always_on_lateral = self.get_value("AlwaysOnLateral")
    toggle.always_on_lateral_set &= toggle.always_on_lateral
    toggle.always_on_lateral_lkas = toggle.always_on_lateral_set and toggle.lkas_allowed_for_aol and self.get_value("AlwaysOnLateralLKAS")
    toggle.always_on_lateral_main = toggle.always_on_lateral_set and not prohibited_main_aol and not toggle.always_on_lateral_lkas and self.get_value("AlwaysOnLateralMain")
    toggle.always_on_lateral_pause_speed = self.get_value("PauseAOLOnBrake", cast=float, condition=toggle.always_on_lateral, conversion=speed_conversion)

    toggle.automatic_updates = self.get_value("AutomaticUpdates", condition=self.release_branch or self.vetting_branch, default=get_default_value("AutomaticUpdates") == "1") and not frogpilot_paths.BACKUP_PATH.is_file()

    toggle.cluster_offset = self.get_value("ClusterOffset", cast=float, condition=toggle.car_make == "toyota")

    toggle.conditional_experimental_mode = toggle.openpilot_longitudinal and self.get_value("ConditionalExperimental")
    toggle.conditional_curves = self.get_value("CECurves", condition=toggle.conditional_experimental_mode)
    toggle.conditional_curves_lead = self.get_value("CECurvesLead", condition=toggle.conditional_curves)
    toggle.conditional_lead = self.get_value("CELead", condition=toggle.conditional_experimental_mode)
    toggle.conditional_slower_lead = self.get_value("CESlowerLead", condition=toggle.conditional_lead)
    toggle.conditional_stopped_lead = self.get_value("CEStoppedLead", condition=toggle.conditional_lead)
    toggle.conditional_limit = self.get_value("CESpeed", cast=float, condition=toggle.conditional_experimental_mode, conversion=speed_conversion)
    toggle.conditional_limit_lead = self.get_value("CESpeedLead", cast=float, condition=toggle.conditional_experimental_mode, conversion=speed_conversion)
    toggle.conditional_navigation = self.get_value("CENavigation", condition=toggle.conditional_experimental_mode)
    toggle.conditional_navigation_intersections = self.get_value("CENavigationIntersections", condition=toggle.conditional_navigation)
    toggle.conditional_navigation_lead = self.get_value("CENavigationLead", condition=toggle.conditional_navigation)
    toggle.conditional_navigation_turns = self.get_value("CENavigationTurns", condition=toggle.conditional_navigation)
    toggle.conditional_stop_lights = self.get_value("CEStopLights", condition=toggle.conditional_experimental_mode)
    toggle.conditional_signal = self.get_value("CESignalSpeed", cast=float, condition=toggle.conditional_experimental_mode, conversion=speed_conversion, default=float(get_default_value("CESignalSpeed")) * CV.MPH_TO_MS)
    toggle.conditional_signal_lane_detection = self.get_value("CESignalLaneDetection", condition=toggle.conditional_experimental_mode and toggle.conditional_signal != 0)
    toggle.cem_status = self.get_value("ShowCEMStatus", condition=toggle.conditional_experimental_mode) or toggle.debug_mode

    toggle.curve_speed_controller = toggle.openpilot_longitudinal and self.get_value("CurveSpeedController")
    toggle.curve_speed_profile = self.get_value("CurveSpeedProfile", cast=int, condition=toggle.curve_speed_controller)
    toggle.csc_status = self.get_value("ShowCSCStatus", condition=toggle.curve_speed_controller) or toggle.debug_mode

    custom_alerts = self.get_value("CustomAlerts")
    toggle.goat_scream_alert = self.get_value("GoatScream", condition=custom_alerts)
    toggle.green_light_alert = self.get_value("GreenLightAlert", condition=custom_alerts)
    toggle.lead_departing_alert = self.get_value("LeadDepartingAlert", condition=custom_alerts)
    toggle.loud_blindspot_alert = self.get_value("LoudBlindspotAlert", condition=has_bsm and custom_alerts)
    toggle.speed_limit_changed_alert = self.get_value("SpeedLimitChangedAlert", condition=custom_alerts)

    toggle.custom_personalities = toggle.openpilot_longitudinal and self.get_value("CustomPersonalities")
    aggressive_profile = toggle.custom_personalities and self.get_value("AggressivePersonalityProfile")
    toggle.aggressive_jerk_acceleration = self.get_value("AggressiveJerkAcceleration", cast=float, condition=aggressive_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.aggressive_jerk_deceleration = self.get_value("AggressiveJerkDeceleration", cast=float, condition=aggressive_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.aggressive_jerk_danger = self.get_value("AggressiveJerkDanger", cast=float, condition=aggressive_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.aggressive_jerk_speed = self.get_value("AggressiveJerkSpeed", cast=float, condition=aggressive_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.aggressive_jerk_speed_decrease = self.get_value("AggressiveJerkSpeedDecrease", cast=float, condition=aggressive_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.aggressive_follow = self.get_value("AggressiveFollow", cast=float, condition=aggressive_profile, minimum=1, maximum=MAX_T_FOLLOW)
    standard_profile = toggle.custom_personalities and self.get_value("StandardPersonalityProfile")
    toggle.standard_jerk_acceleration = self.get_value("StandardJerkAcceleration", cast=float, condition=standard_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.standard_jerk_deceleration = self.get_value("StandardJerkDeceleration", cast=float, condition=standard_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.standard_jerk_danger = self.get_value("StandardJerkDanger", cast=float, condition=standard_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.standard_jerk_speed = self.get_value("StandardJerkSpeed", cast=float, condition=standard_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.standard_jerk_speed_decrease = self.get_value("StandardJerkSpeedDecrease", cast=float, condition=standard_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.standard_follow = self.get_value("StandardFollow", cast=float, condition=standard_profile, minimum=1, maximum=MAX_T_FOLLOW)
    relaxed_profile = toggle.custom_personalities and self.get_value("RelaxedPersonalityProfile")
    toggle.relaxed_jerk_acceleration = self.get_value("RelaxedJerkAcceleration", cast=float, condition=relaxed_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.relaxed_jerk_deceleration = self.get_value("RelaxedJerkDeceleration", cast=float, condition=relaxed_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.relaxed_jerk_danger = self.get_value("RelaxedJerkDanger", cast=float, condition=relaxed_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.relaxed_jerk_speed = self.get_value("RelaxedJerkSpeed", cast=float, condition=relaxed_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.relaxed_jerk_speed_decrease = self.get_value("RelaxedJerkSpeedDecrease", cast=float, condition=relaxed_profile, conversion=0.01, minimum=0.25, maximum=2.0)
    toggle.relaxed_follow = self.get_value("RelaxedFollow", cast=float, condition=relaxed_profile, minimum=1, maximum=MAX_T_FOLLOW)

    custom_themes = self.get_value("CustomThemes")
    toggle.color_scheme = self.get_value("ColorScheme", cast=None, condition=custom_themes)
    theme_colors = json.loads(frogpilot_paths.THEME_COLORS_PATH.read_text()) if frogpilot_paths.THEME_COLORS_PATH.is_file() else {}
    toggle.lane_lines_color = self.get_color("LaneLines", theme_colors)
    toggle.lead_marker_color = self.get_color("LeadMarker", theme_colors)
    toggle.path_color = self.get_color("Path", theme_colors)
    toggle.path_edges_color = self.get_color("PathEdge", theme_colors)
    toggle.sidebar_color1 = self.get_color("Sidebar1", theme_colors)
    toggle.sidebar_color2 = self.get_color("Sidebar2", theme_colors)
    toggle.sidebar_color3 = self.get_color("Sidebar3", theme_colors)
    toggle.distance_icons = self.get_value("DistanceIconPack", cast=None, condition=custom_themes)
    toggle.icon_pack = self.get_value("IconPack", cast=None, condition=custom_themes)
    toggle.signal_icons = self.get_value("SignalAnimation", cast=None, condition=custom_themes)
    toggle.sound_pack = self.get_value("SoundPack", cast=None, condition=custom_themes)
    toggle.random_themes = self.get_value("RandomThemes", condition=custom_themes)
    if toggle.random_themes:
      toggle.color_scheme = "random"
    toggle.random_themes_holidays = self.get_value("RandomThemesHolidays", condition=toggle.random_themes)
    toggle.wheel_image = self.get_value("WheelIcon", cast=None, condition=custom_themes)

    custom_ui = self.get_value("CustomUI")
    toggle.acceleration_path = toggle.openpilot_longitudinal and (self.get_value("AccelerationPath", condition=custom_ui) or toggle.debug_mode)
    toggle.adjacent_paths = self.get_value("AdjacentPath", condition=custom_ui)
    toggle.blind_spot_path = has_bsm and self.get_value("BlindSpotPath", condition=custom_ui)
    toggle.compass = self.get_value("Compass", condition=custom_ui)
    toggle.onroad_distance_button = toggle.openpilot_longitudinal and (self.get_value("OnroadDistanceButton", condition=custom_ui) or toggle.debug_mode)
    toggle.pedals_on_ui = self.get_value("PedalsOnUI", condition=toggle.openpilot_longitudinal and custom_ui)
    toggle.dynamic_pedals_on_ui = self.get_value("DynamicPedalsOnUI", condition=toggle.pedals_on_ui)
    toggle.static_pedals_on_ui = self.get_value("StaticPedalsOnUI", condition=toggle.pedals_on_ui)
    toggle.rotating_wheel = self.get_value("RotatingWheel", condition=custom_ui)

    toggle.developer_ui = self.get_value("DeveloperUI")
    toggle.developer_metrics = self.get_value("DeveloperMetrics", condition=toggle.developer_ui)
    border_metrics = self.get_value("BorderMetrics", condition=toggle.developer_metrics)
    toggle.blind_spot_metrics = has_bsm and self.get_value("BlindSpotMetrics", condition=border_metrics)
    toggle.signal_metrics = self.get_value("SignalMetrics", condition=border_metrics) or toggle.debug_mode
    toggle.steering_metrics = not is_angle_car and (self.get_value("ShowSteering", condition=border_metrics) or toggle.debug_mode)
    toggle.show_fps = self.get_value("FPSCounter", condition=toggle.developer_metrics) or toggle.debug_mode
    toggle.adjacent_path_metrics = self.get_value("AdjacentPathMetrics", condition=toggle.developer_metrics) or toggle.debug_mode
    toggle.lead_info = self.get_value("LeadInfo", condition=toggle.developer_metrics) or toggle.debug_mode
    toggle.numerical_temp = self.get_value("NumericalTemp", condition=toggle.developer_metrics) or toggle.debug_mode
    toggle.fahrenheit = self.get_value("Fahrenheit", condition=toggle.numerical_temp and not toggle.debug_mode)
    toggle.cpu_metrics = self.get_value("ShowCPU", condition=toggle.developer_metrics) or toggle.debug_mode
    toggle.gpu_metrics = self.get_value("ShowGPU", condition=toggle.developer_metrics and not toggle.debug_mode)
    toggle.ip_metrics = self.get_value("ShowIP", condition=toggle.developer_metrics)
    toggle.memory_metrics = self.get_value("ShowMemoryUsage", condition=toggle.developer_metrics) or toggle.debug_mode
    toggle.storage_left_metrics = self.get_value("ShowStorageLeft", condition=toggle.developer_metrics and not toggle.debug_mode)
    toggle.storage_used_metrics = self.get_value("ShowStorageUsed", condition=toggle.developer_metrics and not toggle.debug_mode)
    toggle.use_si_metrics = self.get_value("UseSI", condition=toggle.developer_metrics) or toggle.debug_mode
    toggle.developer_sidebar = self.get_value("DeveloperSidebar", condition=toggle.developer_ui) or toggle.debug_mode
    toggle.developer_sidebar_metric1 = self.get_value("DeveloperSidebarMetric1", cast=int, condition=toggle.developer_sidebar, default=DEVELOPER_SIDEBAR_METRICS["LONGITUDINAL_ACTUATOR_ACCELERATION"] if toggle.debug_mode else None)
    toggle.developer_sidebar_metric2 = self.get_value("DeveloperSidebarMetric2", cast=int, condition=toggle.developer_sidebar, default=DEVELOPER_SIDEBAR_METRICS["ACCELERATION_CURRENT"] if toggle.debug_mode else None)
    toggle.developer_sidebar_metric3 = self.get_value("DeveloperSidebarMetric3", cast=int, condition=toggle.developer_sidebar, default=DEVELOPER_SIDEBAR_METRICS["LATERAL_STEERING_ANGLE"] if toggle.debug_mode else None)
    toggle.developer_sidebar_metric4 = self.get_value("DeveloperSidebarMetric4", cast=int, condition=toggle.developer_sidebar, default=DEVELOPER_SIDEBAR_METRICS["LATERAL_TORQUE_USED"] if toggle.debug_mode else None)
    toggle.developer_sidebar_metric5 = self.get_value("DeveloperSidebarMetric5", cast=int, condition=toggle.developer_sidebar, default=DEVELOPER_SIDEBAR_METRICS["LONGITUDINAL_MPC_JERK_ACCELERATION"] if toggle.debug_mode else None)
    toggle.developer_sidebar_metric6 = self.get_value("DeveloperSidebarMetric6", cast=int, condition=toggle.developer_sidebar, default=DEVELOPER_SIDEBAR_METRICS["LONGITUDINAL_MPC_JERK_DANGER_ZONE"] if toggle.debug_mode else None)
    toggle.developer_sidebar_metric7 = self.get_value("DeveloperSidebarMetric7", cast=int, condition=toggle.developer_sidebar, default=DEVELOPER_SIDEBAR_METRICS["LONGITUDINAL_MPC_JERK_SPEED_CONTROL"] if toggle.debug_mode else None)
    developer_widgets = self.get_value("DeveloperWidgets", condition=toggle.developer_ui)
    toggle.adjacent_lead_tracking = toggle.has_radar and (self.get_value("AdjacentLeadsUI", condition=developer_widgets) or toggle.debug_mode)
    toggle.radar_tracks = toggle.has_radar and (self.get_value("RadarTracksUI", condition=developer_widgets) or toggle.debug_mode)
    toggle.show_stopping_point = toggle.openpilot_longitudinal and (self.get_value("ShowStoppingPoint", condition=developer_widgets) or toggle.debug_mode)
    toggle.show_stopping_point_metrics = self.get_value("ShowStoppingPointMetrics", condition=toggle.show_stopping_point) or toggle.debug_mode

    device_management = self.get_value("DeviceManagement")
    device_shutdown_setting = params.get_int("DeviceShutdown") if device_management and toggle.tuning_level >= level["DeviceShutdown"] else default.get_int("DeviceShutdown")
    toggle.device_shutdown_time = (device_shutdown_setting - 3) * 3600 if device_shutdown_setting >= 4 else (device_shutdown_setting * (60 * 15) or 300)
    toggle.increase_thermal_limits = self.get_value("IncreaseThermalLimits", condition=device_management)
    toggle.low_voltage_shutdown = self.get_value("LowVoltageShutdown", cast=float, condition=device_management, minimum=VBATT_PAUSE_CHARGING, maximum=12.5)
    toggle.no_logging = self.get_value("NoLogging", condition=device_management) and not self.vetting_branch or toggle.force_onroad

    if not started:
      toggle.use_higher_bitrate = device_management
      toggle.use_higher_bitrate &= self.get_value("HigherBitrate")
      toggle.use_higher_bitrate &= self.get_value("NoUploads")
      toggle.use_higher_bitrate &= not self.get_value("DisableOnroadUploads")
      toggle.use_higher_bitrate &= not self.vetting_branch
      toggle.use_higher_bitrate |= self.development_branch

      toggle.use_konik_server = device_management
      toggle.use_konik_server &= self.get_value("UseKonikServer")
      toggle.use_konik_server |= frogpilot_paths.NOT_VETTED_PATH.is_file()

    toggle.no_uploads = self.get_value("NoUploads", condition=device_management) and not self.vetting_branch or toggle.use_higher_bitrate
    toggle.no_onroad_uploads = self.get_value("DisableOnroadUploads", condition=toggle.no_uploads) and not toggle.use_higher_bitrate
    toggle.uploads_disabled = toggle.no_uploads and not toggle.no_onroad_uploads

    toggle.distance_button_function = self.get_button_function("DistanceButtonControl")
    toggle.distance_long_button_function = self.get_button_function("LongDistanceButtonControl")
    toggle.distance_very_long_button_function = self.get_button_function("VeryLongDistanceButtonControl")

    toggle.frogpilot_telemetry = self.get_value("FrogPilotTelemetry", condition=self.params.get_bool("FrogPilotTelemetryConfirmed"))

    toggle.frogsgomoo_tweak = self.get_value("FrogsGoMoosTweak", condition=toggle.openpilot_longitudinal and toggle.car_make == "toyota")
    toggle.stoppingDecelRate = 0.01 if toggle.frogsgomoo_tweak else toggle.stoppingDecelRate
    toggle.vEgoStarting = 0.1 if toggle.frogsgomoo_tweak else toggle.vEgoStarting
    toggle.vEgoStopping = 0.5 if toggle.frogsgomoo_tweak else toggle.vEgoStopping

    toggle.holiday_themes = self.get_value("HolidayThemes")
    toggle.current_holiday_theme = holiday_theme if toggle.holiday_themes else "stock"
    toggle.holiday_greeting = HOLIDAY_GREETINGS.get(toggle.current_holiday_theme, "")
    if toggle.current_holiday_theme != "stock":
      toggle.color_scheme = toggle.current_holiday_theme
      toggle.distance_icons = toggle.current_holiday_theme
      toggle.icon_pack = toggle.current_holiday_theme
      toggle.signal_icons = toggle.current_holiday_theme
      toggle.sound_pack = toggle.current_holiday_theme
      toggle.wheel_image = toggle.current_holiday_theme

    honda_nidec_longitudinal = toggle.openpilot_longitudinal and honda_nidec
    toggle.honda_alt_tune = self.get_value("HondaAltTune", condition=honda_nidec_longitudinal)
    toggle.honda_low_speed_pedal = self.get_value("HondaLowSpeedPedal", condition=toggle.openpilot_longitudinal and toggle.car_make == "honda" and has_pedal)
    toggle.honda_max_brake = self.get_value("HondaMaxBrake", condition=honda_nidec_longitudinal)

    toggle.lane_changes = self.get_value("LaneChanges")
    toggle.lane_change_delay = self.get_value("LaneChangeTime", cast=float, condition=toggle.lane_changes)
    toggle.nudgeless = self.get_value("NudgelessLaneChange", condition=toggle.lane_changes)
    toggle.lane_detection_width = self.get_value("LaneDetectionWidth", cast=float, condition=toggle.nudgeless or toggle.conditional_signal_lane_detection, conversion=distance_conversion)
    toggle.lane_detection = toggle.lane_detection_width > 0
    toggle.minimum_lane_change_speed = self.get_value("MinimumLaneChangeSpeed", cast=float, condition=toggle.lane_changes, conversion=speed_conversion, default=float(get_default_value("MinimumLaneChangeSpeed")) * CV.MPH_TO_MS)
    toggle.one_lane_change = self.get_value("OneLaneChange", condition=toggle.lane_changes)

    lateral_tuning = self.get_value("LateralTune")
    toggle.nnff_selected = self.get_value("NNFF", condition=lateral_tuning)
    toggle.nnff_lite_selected = self.get_value("NNFFLite", condition=lateral_tuning)
    toggle.nnff = toggle.has_nnff and not is_angle_car and toggle.nnff_selected
    toggle.nnff_lite = not is_angle_car and not toggle.nnff and toggle.nnff_lite_selected
    toggle.use_turn_desires = self.get_value("TurnDesires", condition=lateral_tuning)

    if toggle.has_lkas_button and not toggle.always_on_lateral_lkas:
      toggle.lkas_button_function = self.get_button_function("LKASButtonControl")
    else:
      toggle.lkas_button_function = BUTTON_FUNCTIONS["NOTHING"]

    toggle.lock_doors_timer = self.get_value("LockDoorsTimer", cast=int, condition=toggle.car_make == "toyota")

    toggle.long_pitch = self.get_value("LongPitch", condition=toggle.openpilot_longitudinal and toggle.car_make == "gm" and not toggle.is_gm_cc_only)

    longitudinal_tuning = toggle.openpilot_longitudinal and self.get_value("LongitudinalTune")
    toggle.acceleration_profile = self.get_value("AccelerationProfile", cast=float, condition=longitudinal_tuning)
    toggle.deceleration_profile = self.get_value("DecelerationProfile", cast=float, condition=longitudinal_tuning)
    toggle.human_acceleration = self.get_value("HumanAcceleration", condition=longitudinal_tuning)
    toggle.human_following = self.get_value("HumanFollowing", condition=longitudinal_tuning)
    toggle.human_lane_changes = toggle.has_radar and self.get_value("HumanLaneChanges", condition=longitudinal_tuning)
    toggle.lead_detection_probability = self.get_value("LeadDetectionThreshold", cast=float, condition=longitudinal_tuning, conversion=0.01, minimum=0.25, maximum=0.5)
    toggle.taco_tune = self.get_value("TacoTune", condition=longitudinal_tuning)

    toggle.automatically_download_models = self.get_value("AutomaticallyDownloadModels")
    toggle.available_models = (params.get("AvailableModels", encoding="utf-8") or "") + f",{DEFAULT_MODEL}"
    toggle.available_model_names = (params.get("AvailableModelNames", encoding="utf-8") or "") + f",{DEFAULT_MODEL_NAME}"
    model_versions = (params.get("ModelVersions", encoding="utf-8") or "") + f",{DEFAULT_MODEL_VERSION}"
    model_version_lookup = dict(zip(toggle.available_models.split(","), model_versions.split(",")))
    thneed_models = {model for model, version in model_version_lookup.items() if version in THNEED_MODEL_VERSIONS}
    downloaded_models = frogpilot_utilities.get_downloaded_models(toggle.available_models.split(","), thneed_models)
    toggle.model_randomizer = self.get_value("ModelRandomizer")
    if toggle.model_randomizer:
      if not started:
        randomized_model = params.get("RandomizedModel", encoding="utf-8")
        toggle.model = randomized_model if randomized_model in downloaded_models else DEFAULT_MODEL
        toggle.model_name = "Mystery Model 👻"
    elif not started:
      model = (self.get_value("Model", cast=None) or DEFAULT_MODEL).removesuffix("_default")
      if model in downloaded_models:
        toggle.model = model
        toggle.model_name = dict(zip(toggle.available_models.split(","), toggle.available_model_names.split(","))).get(toggle.model, DEFAULT_MODEL_NAME)
      else:
        toggle.model = DEFAULT_MODEL
        toggle.model_name = DEFAULT_MODEL_NAME

    toggle.model_ui = self.get_value("ModelUI")
    toggle.dynamic_path_width = self.get_value("DynamicPathWidth", condition=toggle.model_ui and not toggle.debug_mode)
    toggle.lane_line_width = self.get_value("LaneLinesWidth", cast=float, condition=toggle.model_ui and not toggle.debug_mode, conversion=small_distance_conversion / 200, default=float(get_default_value("LaneLinesWidth")) * CV.INCH_TO_CM / 200)
    toggle.path_edge_width = self.get_value("PathEdgeWidth", cast=float, condition=toggle.model_ui and not toggle.debug_mode, default=float(get_default_value("PathEdgeWidth")) if toggle.debug_mode else None)
    toggle.path_width = self.get_value("PathWidth", cast=float, condition=toggle.model_ui and not toggle.debug_mode, conversion=distance_conversion / 2, default=float(get_default_value("PathWidth")) * CV.FOOT_TO_METER / 2)
    toggle.road_edge_width = self.get_value("RoadEdgesWidth", cast=float, condition=toggle.model_ui and not toggle.debug_mode, conversion=small_distance_conversion / 200, default=float(get_default_value("RoadEdgesWidth")) * CV.INCH_TO_CM / 200)

    navigation_ui = self.get_value("NavigationUI")
    toggle.big_map = self.get_value("BigMap", condition=navigation_ui)
    toggle.full_map = self.get_value("FullMap", condition=toggle.big_map)
    toggle.map_style = self.get_value("MapStyle", cast=int, condition=navigation_ui)
    toggle.road_name_ui = self.get_value("RoadNameUI", condition=navigation_ui) or toggle.debug_mode
    toggle.show_speed_limits = self.get_value("ShowSpeedLimits", condition=navigation_ui) or toggle.debug_mode
    toggle.speed_limit_vienna = self.get_value("UseVienna", condition=navigation_ui)

    if not started or toggle.car_make != "hyundai":
      toggle.old_long_api = toggle.openpilot_longitudinal and toggle.car_make == "gm" and toggle.has_cc_long and not has_pedal
      toggle.old_long_api |= toggle.car_make == "hyundai" and not self.get_value("NewLongAPI")

    quality_of_life_lateral = self.get_value("QOLLateral")
    toggle.pause_lateral_below_speed = self.get_value("PauseLateralSpeed", cast=float, condition=quality_of_life_lateral, conversion=speed_conversion)
    toggle.pause_lateral_below_signal = self.get_value("PauseLateralOnSignal", condition=toggle.pause_lateral_below_speed != 0)

    quality_of_life_longitudinal = toggle.openpilot_longitudinal and self.get_value("QOLLongitudinal")
    toggle.cruise_increase = self.get_value("CustomCruise", cast=float, condition=not pcm_cruise and quality_of_life_longitudinal)
    toggle.cruise_increase_long = self.get_value("CustomCruiseLong", cast=float, condition=not pcm_cruise and quality_of_life_longitudinal)
    toggle.force_stops = self.get_value("ForceStops", condition=quality_of_life_longitudinal)
    toggle.increase_stopped_distance = self.get_value("IncreasedStoppedDistance", cast=float, condition=quality_of_life_longitudinal, conversion=distance_conversion)
    can_map_gears = (toggle.car_make in MAP_GEARS_BRANDS or hyundai_canfd) and not CP.secOcRequired
    map_gears = self.get_value("MapGears", condition=can_map_gears and quality_of_life_longitudinal)
    toggle.map_acceleration = self.get_value("MapAcceleration", condition=map_gears)
    toggle.map_deceleration = self.get_value("MapDeceleration", condition=map_gears)
    toggle.reverse_cruise_increase = self.get_value("ReverseCruise", condition=quality_of_life_longitudinal and toggle.car_make == "toyota" and pcm_cruise)
    toggle.set_speed_offset = self.get_value("SetSpeedOffset", cast=float, condition=not pcm_cruise and quality_of_life_longitudinal, conversion=(1 if toggle.is_metric else CV.MPH_TO_KPH))
    toggle.weather_presets = self.get_value("WeatherPresets", condition=quality_of_life_longitudinal)
    toggle.increase_following_distance_low_visibility = self.get_value("IncreaseFollowingLowVisibility", cast=float, condition=toggle.weather_presets)
    toggle.increase_following_distance_rain = self.get_value("IncreaseFollowingRain", cast=float, condition=toggle.weather_presets)
    toggle.increase_following_distance_rain_storm = self.get_value("IncreaseFollowingRainStorm", cast=float, condition=toggle.weather_presets)
    toggle.increase_following_distance_snow = self.get_value("IncreaseFollowingSnow", cast=float, condition=toggle.weather_presets)
    toggle.increase_stopped_distance_low_visibility = self.get_value("IncreasedStoppedDistanceLowVisibility", cast=float, condition=toggle.weather_presets, conversion=distance_conversion)
    toggle.increase_stopped_distance_rain = self.get_value("IncreasedStoppedDistanceRain", cast=float, condition=toggle.weather_presets, conversion=distance_conversion)
    toggle.increase_stopped_distance_rain_storm = self.get_value("IncreasedStoppedDistanceRainStorm", cast=float, condition=toggle.weather_presets, conversion=distance_conversion)
    toggle.increase_stopped_distance_snow = self.get_value("IncreasedStoppedDistanceSnow", cast=float, condition=toggle.weather_presets, conversion=distance_conversion)
    toggle.reduce_acceleration_low_visibility = self.get_value("ReduceAccelerationLowVisibility", cast=int, condition=toggle.weather_presets) / 100
    toggle.reduce_acceleration_rain = self.get_value("ReduceAccelerationRain", cast=int, condition=toggle.weather_presets) / 100
    toggle.reduce_acceleration_rain_storm = self.get_value("ReduceAccelerationRainStorm", cast=int, condition=toggle.weather_presets) / 100
    toggle.reduce_acceleration_snow = self.get_value("ReduceAccelerationSnow", cast=int, condition=toggle.weather_presets) / 100
    toggle.reduce_lateral_acceleration_low_visibility = self.get_value("ReduceLateralAccelerationLowVisibility", cast=int, condition=toggle.weather_presets) / 100
    toggle.reduce_lateral_acceleration_rain = self.get_value("ReduceLateralAccelerationRain", cast=int, condition=toggle.weather_presets) / 100
    toggle.reduce_lateral_acceleration_rain_storm = self.get_value("ReduceLateralAccelerationRainStorm", cast=int, condition=toggle.weather_presets) / 100
    toggle.reduce_lateral_acceleration_snow = self.get_value("ReduceLateralAccelerationSnow", cast=int, condition=toggle.weather_presets) / 100

    quality_of_life_visuals = self.get_value("QOLVisuals")
    toggle.camera_view = self.get_value("CameraView", cast=float, condition=quality_of_life_visuals and not toggle.debug_mode, default=float(get_default_value("CameraView")) if toggle.debug_mode else None)
    toggle.driver_camera_in_reverse = self.get_value("DriverCamera", condition=quality_of_life_visuals)
    toggle.stopped_timer = self.get_value("StoppedTimer", condition=quality_of_life_visuals)

    toggle.rainbow_path = self.get_value("RainbowPath", condition=not toggle.debug_mode)

    toggle.random_events = self.get_value("RandomEvents")

    screen_management = self.get_value("ScreenManagement")
    toggle.instant_replay = self.get_value("InstantReplay", cast=int, condition=screen_management)
    toggle.screen_brightness = self.get_value("ScreenBrightness", cast=float, condition=screen_management, minimum=1)
    toggle.screen_brightness_onroad = self.get_value("ScreenBrightnessOnroad", cast=float, condition=screen_management and not toggle.force_onroad)
    toggle.screen_recorder = self.get_value("ScreenRecorder", condition=screen_management) or toggle.debug_mode
    toggle.screen_timeout = self.get_value("ScreenTimeout", cast=float, condition=screen_management)
    toggle.screen_timeout_onroad = self.get_value("ScreenTimeoutOnroad", cast=float, condition=screen_management)
    toggle.standby_mode = self.get_value("StandbyMode", condition=screen_management)

    toggle.sng_hack = self.get_value("SNGHack", condition=toggle.openpilot_longitudinal and toggle.car_make == "toyota" and not has_pedal and not has_sng)

    toggle.speed_limit_controller = toggle.openpilot_longitudinal and self.get_value("SpeedLimitController")
    toggle.force_mph_dashboard = self.get_value("ForceMPHDashboard", condition=toggle.speed_limit_controller and toggle.car_make == "toyota")
    toggle.map_speed_lookahead_higher = self.get_value("SLCLookaheadHigher", cast=int, condition=toggle.speed_limit_controller)
    toggle.map_speed_lookahead_lower = self.get_value("SLCLookaheadLower", cast=int, condition=toggle.speed_limit_controller)
    toggle.set_speed_limit = self.get_value("SetSpeedLimit", condition=toggle.speed_limit_controller)
    toggle.show_speed_limit_offset = self.get_value("ShowSLCOffset", condition=toggle.speed_limit_controller) or toggle.debug_mode
    slc_fallback_method = self.get_value("SLCFallback", cast=int, condition=toggle.speed_limit_controller)
    toggle.slc_fallback_experimental_mode = toggle.speed_limit_controller and slc_fallback_method == 1
    toggle.slc_fallback_previous_speed_limit = toggle.speed_limit_controller and slc_fallback_method == 2
    toggle.slc_mapbox_filler = self.get_value("SLCMapboxFiller", condition=toggle.show_speed_limits or toggle.speed_limit_controller)
    speed_limit_confirmation = self.get_value("SLCConfirmation", condition=toggle.speed_limit_controller)
    toggle.speed_limit_confirmation_higher = self.get_value("SLCConfirmationHigher", condition=speed_limit_confirmation)
    toggle.speed_limit_confirmation_lower = self.get_value("SLCConfirmationLower", condition=speed_limit_confirmation)
    slc_override_method = self.get_value("SLCOverride", cast=int, condition=toggle.speed_limit_controller)
    toggle.speed_limit_controller_override_manual = slc_override_method == 1
    toggle.speed_limit_controller_override_set_speed = slc_override_method == 2
    toggle.speed_limit_offset1 = self.get_value("Offset1", cast=int, condition=toggle.speed_limit_controller, conversion=speed_conversion)
    toggle.speed_limit_offset2 = self.get_value("Offset2", cast=int, condition=toggle.speed_limit_controller, conversion=speed_conversion)
    toggle.speed_limit_offset3 = self.get_value("Offset3", cast=int, condition=toggle.speed_limit_controller, conversion=speed_conversion)
    toggle.speed_limit_offset4 = self.get_value("Offset4", cast=int, condition=toggle.speed_limit_controller, conversion=speed_conversion)
    toggle.speed_limit_offset5 = self.get_value("Offset5", cast=int, condition=toggle.speed_limit_controller, conversion=speed_conversion)
    toggle.speed_limit_offset6 = self.get_value("Offset6", cast=int, condition=toggle.speed_limit_controller, conversion=speed_conversion)
    toggle.speed_limit_offset7 = self.get_value("Offset7", cast=int, condition=toggle.speed_limit_controller, conversion=speed_conversion)
    toggle.speed_limit_priority1 = self.get_value("SLCPriority1", cast=None, condition=toggle.speed_limit_controller)
    toggle.speed_limit_priority2 = self.get_value("SLCPriority2", cast=None, condition=toggle.speed_limit_controller)
    toggle.speed_limit_priority3 = self.get_value("SLCPriority3", cast=None, condition=toggle.speed_limit_controller)
    toggle.speed_limit_priority_highest = toggle.speed_limit_priority1 == "Highest"
    toggle.speed_limit_priority_lowest = toggle.speed_limit_priority1 == "Lowest"
    toggle.speed_limit_sources = self.get_value("SpeedLimitSources", condition=toggle.speed_limit_controller) or toggle.debug_mode

    toggle.speed_limit_filler = self.get_value("SpeedLimitFiller")

    toggle.startup_alert_top = (self.get_value("StartupMessageTop", cast=None) or "").strip()
    toggle.startup_alert_bottom = (self.get_value("StartupMessageBottom", cast=None) or "").strip()

    if started:
      toggle.subaru_sng = toggle.car_make == "subaru" and bool(FPCP.safetyConfigs[-1].safetyParam & Panda.FLAG_SUBARU_SNG)
      toggle.taco_tune_hacks = hyundai_canfd and bool(FPCP.safetyConfigs[-1].safetyParam & Panda.FLAG_HYUNDAI_TACO_TUNE_HACK)
    else:
      toggle.subaru_sng = self.get_value("SubaruSNG")
      toggle.taco_tune_hacks = self.get_value("TacoTuneHacks")

    toggle.tailscale_installed = (frogpilot_paths.TAILSCALE_PATH / "tailscaled").is_file() and not frogpilot_paths.UNIT_PATH.exists()

    toyota_doors = self.get_value("ToyotaDoors", condition=toggle.car_make == "toyota")
    toggle.lock_doors = self.get_value("LockDoors", condition=toyota_doors)
    toggle.unlock_doors = self.get_value("UnlockDoors", condition=toyota_doors)

    toggle.can_use_dsu_bypass = toggle.car_make == "toyota" and not toggle.has_sdsu and not CP.flags & (ToyotaFlags.NO_DSU | ToyotaFlags.UNSUPPORTED_DSU)
    toggle.toyota_dsu_bypass = self.get_value("ToyotaDSUBypass")

    toggle.volt_sng = self.get_value("VoltSNG", condition=toggle.car_model == "CHEVROLET_VOLT" and not has_sng)

    params_memory.put("FrogPilotToggles", json.dumps(toggle.__dict__))
    self.toggles_update_time = time.monotonic_ns()
