#pragma once

#include "frogpilot/selfdrive/ui/qt/offroad/frogpilot_settings.h"

class FrogPilotUtilitiesPanel : public FrogPilotListWidget {
  Q_OBJECT

public:
  explicit FrogPilotUtilitiesPanel(FrogPilotSettingsWindow *parent);

private:
  bool actionRunning = false;

  FrogPilotSettingsWindow *parent = nullptr;

  Params params;
  Params params_memory{"/dev/shm/params"};
};
