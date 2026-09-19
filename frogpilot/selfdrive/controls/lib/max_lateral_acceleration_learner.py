#!/usr/bin/env python3
import json
from collections import deque

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.drive_helpers import MAX_LATERAL_ACCEL_NO_ROLL
from openpilot.selfdrive.controls.lib.vehicle_model import ACCELERATION_DUE_TO_GRAVITY

from openpilot.frogpilot.common.frogpilot_variables import CRUISING_SPEED, params

MAX_LIMIT_STORE_THRESHOLD = 0.01
TRACKING_RATIO = 0.9

MIN_LEARNING_TIME = 1.0


class MaxLateralAccelerationLearner:
  def __init__(self, CurveSpeedController):
    self.csc = CurveSpeedController

    self.angle_observations = deque(maxlen=int(MIN_LEARNING_TIME / DT_MDL))

    self.stored_max_limit = None

    self.learned_profile = json.loads(params.get("MaxLateralAcceleration") or "{}")

  def update(self, sm, frogpilot_toggles):
    learned = False
    valid = False

    if sm["controlsState"].lateralControlState.which() == "angleState":
      max_limit = frogpilot_toggles.maxLateralAccel
      if self.learned_profile.get("car_fingerprint") == frogpilot_toggles.car_model:
        max_limit = self.learned_profile.get("value", max_limit)

      valid = sm.all_checks(["carState", "controlsState", "liveLocationKalman", "liveParameters"])
      valid &= sm["controlsState"].lateralControlState.angleState.active and sm["liveParameters"].valid
      valid &= sm["liveLocationKalman"].angularVelocityCalibrated.valid and len(sm["liveLocationKalman"].angularVelocityCalibrated.value) > 2
      valid &= sm["carState"].vEgo > CRUISING_SPEED and not sm["carState"].steeringPressed
      valid &= not (sm["carState"].leftBlinker or sm["carState"].rightBlinker)

      if valid:
        roll_compensation = sm["liveParameters"].roll * ACCELERATION_DUE_TO_GRAVITY

        actual_lateral_acceleration = sm["liveLocationKalman"].angularVelocityCalibrated.value[2] * sm["carState"].vEgo - roll_compensation
        desired_lateral_acceleration = sm["controlsState"].desiredCurvature * sm["carState"].vEgo**2 - roll_compensation
        modeled_lateral_acceleration = sm["controlsState"].curvature * sm["carState"].vEgo**2 - roll_compensation

        valid &= actual_lateral_acceleration * desired_lateral_acceleration > 0
        valid &= modeled_lateral_acceleration * desired_lateral_acceleration > 0

      if valid:
        demonstrated_limit = min(abs(actual_lateral_acceleration), abs(modeled_lateral_acceleration), abs(desired_lateral_acceleration))
        maximum_response = max(abs(actual_lateral_acceleration), abs(modeled_lateral_acceleration))
        steering_angle_magnitude = abs(sm["controlsState"].lateralControlState.angleState.steeringAngleDeg - sm["liveParameters"].angleOffsetDeg)

        self.angle_observations.append((
          desired_lateral_acceleration, demonstrated_limit, maximum_response, steering_angle_magnitude,
          sm["controlsState"].lateralControlState.angleState.saturated,
        ))

        if len(self.angle_observations) == self.angle_observations.maxlen:
          requested_accelerations, demonstrated_limits, maximum_responses, steering_angles, saturated = zip(*self.angle_observations, strict=False)

          tracking = all(demonstrated >= TRACKING_RATIO * abs(requested)
                         for demonstrated, requested in zip(demonstrated_limits, requested_accelerations, strict=False))
          if tracking:
            max_limit = max(max_limit, min(demonstrated_limits))
          elif all(saturated) and min(requested_accelerations) * max(requested_accelerations) > 0:
            interval_maximum_response = max(maximum_responses)
            persistent_deficit = interval_maximum_response < TRACKING_RATIO * min(abs(requested) for requested in requested_accelerations)
            stable_steering = min(steering_angles) >= TRACKING_RATIO * max(steering_angles)
            if persistent_deficit and stable_steering:
              max_limit = min(max_limit, interval_maximum_response)

      learned = True
    elif sm["controlsState"].lateralControlState.which() == "torqueState" and (sm["liveTorqueParameters"].useParams or frogpilot_toggles.force_auto_tune):
      max_limit = sm["liveTorqueParameters"].latAccelFactorFiltered

      learned = True
    else:
      max_limit = frogpilot_toggles.maxLateralAccel

    if not valid:
      self.angle_observations.clear()

    self.csc.max_limit = min(max_limit, MAX_LATERAL_ACCEL_NO_ROLL)

    if learned:
      if self.learned_profile.get("car_fingerprint") != frogpilot_toggles.car_model:
        self.stored_max_limit = None

      self.learned_profile = {
        "car_fingerprint": frogpilot_toggles.car_model,
        "value": self.csc.max_limit,
      }

      if self.stored_max_limit is None or abs(self.csc.max_limit - self.stored_max_limit) >= MAX_LIMIT_STORE_THRESHOLD:
        self.stored_max_limit = self.csc.max_limit
        params.put_nonblocking("MaxLateralAcceleration", json.dumps(self.learned_profile))
