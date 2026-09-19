#!/usr/bin/env python3
from openpilot.common.realtime import DT_MDL

from openpilot.frogpilot.common.frogpilot_utilities import calculate_curve_speed
from openpilot.frogpilot.common.frogpilot_variables import CURVE_SPEED_PROFILES, DECEL_TIME_MARGIN, DEFAULT_LATERAL_ACCELERATION
from openpilot.frogpilot.selfdrive.controls.lib.curve_speed_profile_learner import CurveSpeedProfileLearner
from openpilot.frogpilot.selfdrive.controls.lib.max_lateral_acceleration_learner import MaxLateralAccelerationLearner

CURVE_SPEED_LATERAL_ACCELERATIONS = {
  CURVE_SPEED_PROFILES["GENTLE"]: 1.75,
  CURVE_SPEED_PROFILES["STANDARD"]: DEFAULT_LATERAL_ACCELERATION
}

TARGET_RISE_RATE = 1.2

class CurveSpeedController:
  def __init__(self, FrogPilotVCruise):
    self.frogpilot_planner = FrogPilotVCruise.frogpilot_planner

    self.lateral_acceleration = DEFAULT_LATERAL_ACCELERATION
    self.max_limit = DEFAULT_LATERAL_ACCELERATION

    self.enable_training = False

    self.target = None

    self.max_limit_learner = MaxLateralAccelerationLearner(self)
    self.profile_learner = CurveSpeedProfileLearner(self)

  def update_lateral_acceleration(self, frogpilot_toggles):
    if frogpilot_toggles.curve_speed_profile == CURVE_SPEED_PROFILES["AUTO"]:
      self.lateral_acceleration = self.profile_learner.calibrated_lateral_acceleration
    elif frogpilot_toggles.curve_speed_profile == CURVE_SPEED_PROFILES["SPORT"]:
      self.lateral_acceleration = self.max_limit
    else:
      self.lateral_acceleration = CURVE_SPEED_LATERAL_ACCELERATIONS.get(frogpilot_toggles.curve_speed_profile, DEFAULT_LATERAL_ACCELERATION)

    self.lateral_acceleration = min(self.lateral_acceleration, self.max_limit)

    if self.frogpilot_planner.frogpilot_weather.weather_id != 0:
      self.lateral_acceleration -= self.lateral_acceleration * self.frogpilot_planner.frogpilot_weather.reduce_lateral_acceleration

  def update_target(self, v_cruise, v_ego):
    csc_speed = float(calculate_curve_speed(self.frogpilot_planner.road_curvature, self.lateral_acceleration, self.frogpilot_planner.roll_compensation))

    if self.target is None:
      self.target = max(v_ego, csc_speed)

    if csc_speed < self.target:
      decel_rate = max(v_ego - csc_speed, 0) / max(self.frogpilot_planner.time_to_curve - DECEL_TIME_MARGIN, 1)

      self.target = max(min(self.target, v_ego) - decel_rate * DT_MDL, csc_speed)
    elif abs(self.frogpilot_planner.lateral_acceleration - self.frogpilot_planner.roll_compensation) < self.lateral_acceleration:
      self.target = min(self.target + TARGET_RISE_RATE * DT_MDL, csc_speed)

      if self.target >= v_cruise:
        self.target = csc_speed

    return self.target
