#pragma once

#include <memory>

#include <QObject>

#include "cereal/messaging/messaging.h"
#include "selfdrive/ui/qt/network/wifi_manager.h"

#include "frogpilot/selfdrive/ui/qt/widgets/frogpilot_controls.h"

struct RadarTrackData {
  QPointF calibrated_point;
};

struct FrogPilotUIScene {
  bool always_on_lateral_active = false;
  bool downloading_update = false;
  bool enabled = false;
  bool frogpilot_panel_active = false;
  bool map_open = false;
  bool online = false;
  bool parked = false;
  bool reverse = false;
  bool sidebars_open = false;
  bool standstill = false;
  bool traffic_mode_enabled = false;
  bool use_stock_colors = false;
  bool wake_up_screen = false;

  float lane_width_left = 0;
  float lane_width_right = 0;

  int conditional_status = 0;
  int driver_camera_timer = 0;
  int model_length = 0;
  int started_timer = 0;

  std::vector<RadarTrackData> live_radar_tracks;

  QColor lane_lines_color;
  QColor lead_marker_color;
  QColor path_color;
  QColor path_edges_color;
  QColor sidebar_color1;
  QColor sidebar_color2;
  QColor sidebar_color3;

  QJsonObject frogpilot_toggles;

  QPointF lead_vertices[2];

  QPolygonF track_adjacent_vertices[2];
  QPolygonF track_edge_vertices;
};

class FrogPilotUIState : public QObject {
  Q_OBJECT

public:
  explicit FrogPilotUIState(QObject *parent = nullptr);

  void update();

  std::unique_ptr<SubMaster> sm;

  FrogPilotUIScene frogpilot_scene = {};

  Params params_memory{"/dev/shm/params"};

  QJsonObject &frogpilot_toggles = frogpilot_scene.frogpilot_toggles;

  WifiManager *wifi = nullptr;

signals:
  void themeUpdated();
};

FrogPilotUIState *frogpilotUIState();

void update_theme(FrogPilotUIState *fs);
