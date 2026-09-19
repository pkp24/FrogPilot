#pragma once

#include <QElapsedTimer>

#include "selfdrive/ui/qt/sidebar.h"

class DeveloperSidebar : public QFrame {
  Q_OBJECT

public:
  explicit DeveloperSidebar(QWidget* parent = 0);

private:
  void drawMetric(QPainter &p, const QPair<QString, QString> &label, QColor c, int y);
  void paintEvent(QPaintEvent *event) override;
  void resetVariables();
  void showEvent(QShowEvent *event);
  void updateState(const UIState &s, const FrogPilotUIState &fs);
  void updateTheme();

  double lateralEngagementTime = 0;
  double longitudinalEngagementTime = 0;
  double maxAcceleration = 0;
  double totalEngagementTime = 0;

  int maxSteerAngle = 0;
  int maxTorque = 0;

  std::vector<int> metricAssignments;

  QColor metricColor;

  QElapsedTimer torqueTimer;

  ItemStatus accelerationJerkStatus;
  ItemStatus accelerationStatus;
  ItemStatus actuatorAccelerationStatus;
  ItemStatus dangerJerkStatus;
  ItemStatus delayStatus;
  ItemStatus frictionStatus;
  ItemStatus latAccelStatus;
  ItemStatus lateralEngagementStatus;
  ItemStatus longitudinalEngagementStatus;
  ItemStatus maxAccelerationStatus;
  ItemStatus speedJerkStatus;
  ItemStatus steerAngleStatus;
  ItemStatus steerRatioStatus;
  ItemStatus stiffnessFactorStatus;
  ItemStatus torqueStatus;
};
