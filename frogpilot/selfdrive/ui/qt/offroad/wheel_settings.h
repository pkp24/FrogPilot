#pragma once

#include <set>

#include "frogpilot/selfdrive/ui/qt/offroad/frogpilot_settings.h"

class FrogPilotWheelPanel : public FrogPilotListWidget {
  Q_OBJECT

public:
  explicit FrogPilotWheelPanel(FrogPilotSettingsWindow *parent);

protected:
  void showEvent(QShowEvent *event) override;

private:
  void updateToggles();
  void updateButtonValues();

  bool forceOpenDescriptions = false;

  std::map<QString, AbstractControl*> toggles;

  FrogPilotSettingsWindow *parent = nullptr;

  Params params;

  QJsonObject frogpilotToggleLevels;

  QMap<int, QString> buttonFunctions();
};
