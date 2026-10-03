#pragma once

#include "selfdrive/ui/ui.h"

class FrogPilotModelReview : public QFrame {
  Q_OBJECT

public:
  explicit FrogPilotModelReview(QWidget *parent = nullptr);

signals:
  void driveRated();

protected:
  void mousePressEvent(QMouseEvent *e) override;
  void showEvent(QShowEvent *event) override;

private slots:
  void onBlacklistButtonClicked();
  void onRatingButtonClicked();

private:
  int getModelRank();

  void updateLabel();

  bool modelRated = false;

  int totalDrives = 0;
  int totalOverallDrives = 0;

  Params params;

  QJsonObject currentModelData;
  QJsonObject modelDrivesAndScores;

  QLabel *blacklistMessageLabel = nullptr;
  QLabel *modelLabel = nullptr;
  QLabel *modelRankLabel = nullptr;
  QLabel *modelRatingLabel = nullptr;
  QLabel *totalDrivesLabel = nullptr;
  QLabel *totalOverallDrivesLabel = nullptr;

  QPushButton *blacklistButton = nullptr;

  QStackedLayout *mainLayout = nullptr;

  QString currentModel;
  QString currentModelFiltered;

  QStringList availableModelNames;
  QStringList blacklistedModels;
};
