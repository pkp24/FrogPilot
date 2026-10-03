#pragma once

#include "frogpilot/selfdrive/ui/qt/offroad/frogpilot_settings.h"

class FrogPilotNavigationPanel : public FrogPilotListWidget {
  Q_OBJECT

public:
  explicit FrogPilotNavigationPanel(FrogPilotSettingsWindow *parent);

signals:
  void closeSubPanel();
  void openSubPanel();

protected:
  void hideEvent(QHideEvent *event);
  void showEvent(QShowEvent *event) override;

private:
  void createKeyControl(ButtonControl *&control, const QString &label, const std::string &paramKey, const QString &prefix, const int &minLength, FrogPilotListWidget *list);
  void mousePressEvent(QMouseEvent *event);
  void updateButtons();
  void updateState(const UIState &s, const FrogPilotUIState &fs);
  void updateStep();

  bool forceOpenDescriptions = false;
  bool mapboxPublicKeySet = false;
  bool mapboxSecretKeySet = false;
  bool setupCompleted = false;

  std::map<QString, AbstractControl*> toggles;

  ButtonControl *amapKeyControl1 = nullptr;
  ButtonControl *amapKeyControl2 = nullptr;
  ButtonControl *setupButton = nullptr;

  ParamControl *updateSpeedLimitsToggle = nullptr;

  FrogPilotButtonsControl *publicMapboxKeyControl = nullptr;
  FrogPilotButtonsControl *secretMapboxKeyControl = nullptr;

  FrogPilotButtonsControl *searchInput = nullptr;

  FrogPilotSettingsWindow *parent = nullptr;

  LabelControl *ipLabel = nullptr;

  Params params;
  Params params_cache{"/cache/params"};
  Params params_memory{"/dev/shm/params"};

  QLabel *imageLabel = nullptr;

  QNetworkAccessManager *networkManager = nullptr;

  QStackedLayout *primelessLayout = nullptr;

  QString currentStep;
};
