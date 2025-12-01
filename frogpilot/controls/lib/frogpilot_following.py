#!/usr/bin/env python3
from cereal import log
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import desired_follow_distance

from openpilot.frogpilot.common import frogpilot_variables

class FrogPilotFollowing:
  def __init__(self, FrogPilotPlanner):
    self.frogpilot_planner = FrogPilotPlanner

    self.following_lead = False

    self.acceleration_jerk = 0
    self.danger_jerk = 0
    self.desired_follow_distance = 0
    self.speed_jerk = 0
    self.t_follow = 0

  def update(self, long_control_active, v_ego, sm, frogpilot_toggles):
    personality = sm["selfdriveState"].personality

    if personality == log.LongitudinalPersonality.aggressive:
      if sm["carState"].aEgo >= 0:
        self.acceleration_jerk = frogpilot_toggles.aggressive_jerk_acceleration
        self.speed_jerk = frogpilot_toggles.aggressive_jerk_speed
      else:
        self.acceleration_jerk = frogpilot_toggles.aggressive_jerk_deceleration
        self.speed_jerk = frogpilot_toggles.aggressive_jerk_speed_decrease

      self.danger_jerk = frogpilot_toggles.aggressive_jerk_danger
      self.t_follow = frogpilot_toggles.aggressive_follow
    elif personality == log.LongitudinalPersonality.standard:
      if sm["carState"].aEgo >= 0:
        self.acceleration_jerk = frogpilot_toggles.standard_jerk_acceleration
        self.speed_jerk = frogpilot_toggles.standard_jerk_speed
      else:
        self.acceleration_jerk = frogpilot_toggles.standard_jerk_deceleration
        self.speed_jerk = frogpilot_toggles.standard_jerk_speed_decrease

      self.danger_jerk = frogpilot_toggles.standard_jerk_danger
      self.t_follow = frogpilot_toggles.standard_follow
    elif personality == log.LongitudinalPersonality.relaxed:
      if sm["carState"].aEgo >= 0:
        self.acceleration_jerk = frogpilot_toggles.relaxed_jerk_acceleration
        self.speed_jerk = frogpilot_toggles.relaxed_jerk_speed
      else:
        self.acceleration_jerk = frogpilot_toggles.relaxed_jerk_deceleration
        self.speed_jerk = frogpilot_toggles.relaxed_jerk_speed_decrease

      self.danger_jerk = frogpilot_toggles.relaxed_jerk_danger
      self.t_follow = frogpilot_toggles.relaxed_follow

    self.following_lead = self.frogpilot_planner.lead_one.status
    self.following_lead &= self.frogpilot_planner.lead_one.dRel < (self.t_follow * 2) * v_ego

    if long_control_active and self.frogpilot_planner.lead_one.status:
      self.desired_follow_distance = desired_follow_distance(v_ego, self.frogpilot_planner.lead_one.vLead, self.t_follow)
    else:
      self.desired_follow_distance = 0
