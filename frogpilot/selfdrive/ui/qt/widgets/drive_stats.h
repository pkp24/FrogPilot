#pragma once

#include "selfdrive/ui/ui.h"

struct StatsLabels {
  QLabel *distance = nullptr;
  QLabel *distance_unit = nullptr;
  QLabel *hours = nullptr;
  QLabel *routes = nullptr;
};

class DriveStats : public QFrame {
  Q_OBJECT

public:
  explicit DriveStats(QWidget *parent = 0);

private:
  void addStatsLayouts(const QString &title, StatsLabels &labels, bool FrogPilot = false);
  void showEvent(QShowEvent *event) override;
  void updateFrogPilotStatsForLabel(StatsLabels &labels);
  void updateStats();
  void updateStatsForLabel(const QJsonObject &obj, StatsLabels &labels);

  bool isMetric = false;
  bool konik = false;

  Params params;

  QJsonDocument stats;

  StatsLabels all;
  StatsLabels frogPilot;
  StatsLabels week;

private slots:
  void parseResponse(const QString &response, bool success);
};
