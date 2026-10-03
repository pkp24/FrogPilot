#!/usr/bin/env python3
import numpy as np

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import STOP_DISTANCE

from openpilot.frogpilot.common.frogpilot_variables import CRUISING_SPEED, THRESHOLD, params_memory

KINEMATIC_LEAD_DECELERATION = 2.0
LEAD_SPEED_DIFFERENCE = 2.0

SLOWDOWN_PERCENTAGE = 0.50
SLOWDOWN_RELEASE_PERCENTAGE = 0.75

class ConditionalExperimentalMode:
  def __init__(self, FrogPilotPlanner):
    self.frogpilot_planner = FrogPilotPlanner

    self.curvature_filter = FirstOrderFilter(0, 0.9, DT_MDL)
    self.slow_lead_filter = FirstOrderFilter(0, 0.6, DT_MDL)
    self.stop_light_filter = FirstOrderFilter(0, 0.5, DT_MDL)

    self.curve_detected = False
    self.experimental_mode = False
    self.slow_lead_detected = False
    self.stop_light_detected = False
    self.stop_light_signal = False

  def update(self, v_ego, sm, frogpilot_toggles):
    self.status_value = params_memory.get_int("CEStatus")

    if not sm["carState"].standstill:
      self.curve_detection(v_ego, frogpilot_toggles)
      self.slow_lead(v_ego, sm, frogpilot_toggles)
      self.stop_sign_and_light(v_ego, sm, frogpilot_toggles.conditional_model_stop_time)

    if self.status_value in (1, 2):
      self.experimental_mode = self.status_value == 2
      self.stop_light_detected = False
    else:
      if sm["carState"].standstill:
        self.experimental_mode &= self.frogpilot_planner.model_stopped or self.frogpilot_planner.frogpilot_vcruise.forcing_stop

        if frogpilot_toggles.conditional_model_stop_time != 0 and not sm["frogpilotCarState"].trafficModeEnabled and sm["modelV2"].action.shouldStop:
          self.experimental_mode = True
          self.status_value = 11 if not self.frogpilot_planner.frogpilot_vcruise.forcing_stop else 12
      else:
        self.experimental_mode = self.check_conditions(v_ego, sm, frogpilot_toggles)

      params_memory.put_int("CEStatus", self.status_value if self.experimental_mode else 0)

    if sm["carState"].standstill:
      self.stop_light_filter.x = 0

  def check_conditions(self, v_ego, sm, frogpilot_toggles):
    below_speed = not self.frogpilot_planner.frogpilot_following.following_lead and 1 <= v_ego < frogpilot_toggles.conditional_limit
    below_speed_with_lead = self.frogpilot_planner.frogpilot_following.following_lead and 1 <= v_ego < frogpilot_toggles.conditional_limit_lead
    if below_speed or below_speed_with_lead:
      self.status_value = 3 if self.frogpilot_planner.frogpilot_following.following_lead else 4
      return True

    if v_ego < frogpilot_toggles.conditional_signal and (sm["carState"].leftBlinker or sm["carState"].rightBlinker):
      desired_lane = self.frogpilot_planner.lane_width_left if sm["carState"].leftBlinker else self.frogpilot_planner.lane_width_right

      if desired_lane < frogpilot_toggles.lane_detection_width or not frogpilot_toggles.conditional_signal_lane_detection:
        self.status_value = 5
        return True

    approaching_maneuver = sm["frogpilotNavigation"].approachingIntersection or sm["frogpilotNavigation"].approachingTurn
    if approaching_maneuver and (not self.frogpilot_planner.frogpilot_following.following_lead or frogpilot_toggles.conditional_navigation_lead) and frogpilot_toggles.conditional_navigation:
      self.status_value = 6 if sm["frogpilotNavigation"].approachingIntersection else 7
      return True

    if self.curve_detected and (not self.frogpilot_planner.frogpilot_following.following_lead or frogpilot_toggles.conditional_curves_lead) and frogpilot_toggles.conditional_curves:
      self.status_value = 8
      return True

    if self.slow_lead_detected and frogpilot_toggles.conditional_lead:
      self.status_value = 9 if self.frogpilot_planner.lead_one.vLead < 1 else 10
      return True

    if self.stop_light_detected and frogpilot_toggles.conditional_model_stop_time != 0:
      self.status_value = 11 if not self.frogpilot_planner.frogpilot_vcruise.forcing_stop else 12
      return True

    if self.frogpilot_planner.frogpilot_vcruise.slc.experimental_mode:
      self.status_value = 13
      return True

    return False

  def curve_detection(self, v_ego, frogpilot_toggles):
    self.curvature_filter.update(self.frogpilot_planner.driving_in_curve or self.frogpilot_planner.road_curvature_detected)
    self.curve_detected = self.curvature_filter.x >= THRESHOLD and v_ego > CRUISING_SPEED

  def slow_lead(self, v_ego, sm, frogpilot_toggles):
    if self.frogpilot_planner.tracking_lead and self.frogpilot_planner.lead_one.status:
      predicted_lead_speed = self.frogpilot_planner.lead_one.vLead
      if sm["modelV2"].leadsV3[0].prob > frogpilot_toggles.lead_detection_probability and frogpilot_toggles.model_version == "v9":
        predicted_lead_speed = max(self.frogpilot_planner.lead_one.vLead + min(sm["modelV2"].leadsV3[0].v) - sm["modelV2"].leadsV3[0].v[0], 0)

      required_deceleration = (v_ego**2 - self.frogpilot_planner.lead_one.vLead**2) / (2 * max(self.frogpilot_planner.lead_one.dRel - STOP_DISTANCE, 1))

      slower_lead = v_ego - self.frogpilot_planner.lead_one.vLead >= LEAD_SPEED_DIFFERENCE
      slower_lead |= self.frogpilot_planner.lead_one.vLead - predicted_lead_speed >= LEAD_SPEED_DIFFERENCE
      slower_lead |= required_deceleration >= KINEMATIC_LEAD_DECELERATION and self.frogpilot_planner.lead_one.vLead >= 1 and v_ego > CRUISING_SPEED
      slower_lead &= frogpilot_toggles.conditional_slower_lead

      stopped_lead = predicted_lead_speed < (2.0 if self.slow_lead_detected else 1)
      stopped_lead &= frogpilot_toggles.conditional_stopped_lead

      self.slow_lead_filter.update(slower_lead or stopped_lead)
    elif not self.frogpilot_planner.tracking_lead:
      self.slow_lead_filter.x = 0

    self.slow_lead_detected = self.slow_lead_filter.x >= (1 - THRESHOLD if self.slow_lead_detected else THRESHOLD)

  def stop_sign_and_light(self, v_ego, sm, model_time):
    if not sm["frogpilotCarState"].trafficModeEnabled:
      model_velocities = [velocity for time, velocity in zip(sm["modelV2"].velocity.t, sm["modelV2"].velocity.x) if time < model_time]
      model_velocities.append(np.interp(model_time, sm["modelV2"].velocity.t, sm["modelV2"].velocity.x))

      slowdown_percentage = SLOWDOWN_RELEASE_PERCENTAGE if self.stop_light_filter.x >= THRESHOLD else SLOWDOWN_PERCENTAGE
      model_slowing = min(model_velocities) <= slowdown_percentage * v_ego and not self.curve_detected
      model_stopping = max(np.interp([0.5, 1.5], sm["modelV2"].velocity.t, sm["modelV2"].velocity.x)) < 1

      self.stop_light_signal = bool(model_slowing or model_stopping)
      self.stop_light_filter.update(self.stop_light_signal)
      self.stop_light_detected = self.stop_light_filter.x >= THRESHOLD and not self.frogpilot_planner.tracking_lead
    else:
      self.stop_light_detected = False
      self.stop_light_signal = False

      self.stop_light_filter.x = 0
