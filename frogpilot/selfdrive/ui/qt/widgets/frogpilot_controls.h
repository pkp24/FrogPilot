#pragma once

#include <map>
#include <string>
#include <utility>
#include <vector>

#include <QTimer>

#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/widgets/controls.h"

#include "frogpilot/selfdrive/ui/qt/widgets/frogpilot_helpers.h"

template <typename T>
void openDescriptions(bool forceOpenDescriptions, const std::map<QString, T> &toggles) {
  if (forceOpenDescriptions) {
    for (const std::pair<const QString, T> &entry : toggles) {
      if (AbstractControl *control = qobject_cast<AbstractControl*>(entry.second)) {
        control->showDescription();
      }
    }
  }
}

extern const QString buttonStyle;

class FrogPilotConfirmationDialog : public ConfirmationDialog {
  Q_OBJECT

public:
  static bool toggleReboot(QWidget *parent);
  static bool yesorno(const QString &prompt_text, QWidget *parent);
};

class FrogPilotListWidget : public QWidget {
  Q_OBJECT

public:
  explicit FrogPilotListWidget(QWidget *parent = nullptr) : QWidget(parent), outer_layout(this) {
    outer_layout.setMargin(0);
    outer_layout.setSpacing(0);
    outer_layout.addLayout(&inner_layout);
    inner_layout.setMargin(0);
    inner_layout.setSpacing(25);
    outer_layout.addStretch();
  }

  void addItem(QWidget *widget, bool expanding = false) {
    inner_layout.addWidget(widget);
    if (expanding) {
      widget->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Expanding);
    } else {
      inner_layout.setAlignment(widget, Qt::AlignTop);
    }
  }

  inline void addItem(QLayout *layout) { inner_layout.addLayout(layout); }

  void clear() {
    while (QLayoutItem *item = inner_layout.takeAt(0)) {
      if (QWidget *widget = item->widget()) {
        widget->hide();
        widget->deleteLater();
      }
      delete item;
    }
    update();
  }

private:
  void showEvent(QShowEvent *) override {
    for (QWidget *widget : findChildren<QWidget*>(QString(), Qt::FindDirectChildrenOnly)) {
      if (QLayout *layout = widget->layout()) {
        layout->activate();
      }
    }
    outer_layout.activate();
  }

  void paintEvent(QPaintEvent *) override {
    QPainter painter(this);
    painter.setPen(Qt::gray);
    const int item_count = inner_layout.count();
    int visible_widgets_ahead = 0;
    for (int i = 0; i < item_count; ++i) {
      QWidget *widget = inner_layout.itemAt(i)->widget();
      if (widget != nullptr && widget->isVisible()) {
        ++visible_widgets_ahead;
      }
    }

    for (int i = 0; i < item_count - 1; ++i) {
      QLayoutItem *item = inner_layout.itemAt(i);
      QWidget *widget = item->widget();
      const bool visible = widget != nullptr && widget->isVisible();
      visible_widgets_ahead -= visible;

      if (widget == nullptr || (visible && visible_widgets_ahead > 0)) {
        const QRect rect = item->geometry();
        const int separator_y = rect.bottom() + inner_layout.spacing() / 2;
        painter.drawLine(rect.left() + 40, separator_y, rect.right() - 40, separator_y);
      }
    }
  }

  QVBoxLayout outer_layout;
  QVBoxLayout inner_layout;
};

class FrogPilotButtonGroup {
public:
  void clearCheckedButtons(bool clear_exclusivity = false) {
    const bool exclusive = button_group->exclusive();
    if (clear_exclusivity) {
      button_group->setExclusive(false);
    }

    for (QAbstractButton *button : button_group->buttons()) {
      button->setChecked(false);
    }

    if (clear_exclusivity) {
      button_group->setExclusive(exclusive);
    }
  }

  void setButtonsEnabled(bool enable) {
    for (QAbstractButton *button : button_group->buttons()) {
      button->setEnabled(enable);
    }
  }

  void setCheckedButton(int id) {
    if (QAbstractButton *button = button_group->button(id)) {
      button->setChecked(true);
    }
  }

  void setEnabledButtons(int id, bool enable) {
    if (QAbstractButton *button = button_group->button(id)) {
      button->setEnabled(enable);
    }
  }

  void setText(int id, const QString &text) {
    if (QAbstractButton *button = button_group->button(id)) {
      button->setText(text);
    }
  }

  void setVisibleButton(int id, bool visible) {
    if (QAbstractButton *button = button_group->button(id)) {
      button->setVisible(visible);
    }
  }

protected:
  void buildButtons(QWidget *owner, QBoxLayout *layout, const std::vector<QString> &button_texts,
                    bool checkable, bool exclusive, int minimum_button_width) {
    button_group = new QButtonGroup(owner);
    button_group->setExclusive(exclusive);

    for (int id = 0; id < static_cast<int>(button_texts.size()); ++id) {
      QPushButton *button = new QPushButton(button_texts[id], owner);
      button->setCheckable(checkable);
      button->setStyleSheet(buttonStyle);
      button->setMinimumWidth(minimum_button_width);
      layout->addWidget(button);
      button_group->addButton(button, id);
    }
  }

  QButtonGroup *button_group = nullptr;
};

class FrogPilotButtonControl : public ParamControl, public FrogPilotButtonGroup {
  Q_OBJECT

public:
  FrogPilotButtonControl(const QString &param, const QString &title, const QString &desc, const QString &icon,
                         const std::vector<QString> &button_texts, bool checkable = false,
                         bool exclusive = false, int minimum_button_width = 225)
      : ParamControl(param, title, desc, icon) {
    buildButtons(this, hlayout, button_texts, checkable, exclusive, minimum_button_width);

    hlayout->removeWidget(&toggle);
    hlayout->addWidget(&toggle);

    QObject::connect(button_group, QOverload<int>::of(&QButtonGroup::buttonClicked), this, &FrogPilotButtonControl::onButtonClicked);
    QObject::connect(this, &ToggleControl::toggleFlipped, this, &FrogPilotButtonControl::refresh);
  }

  void refresh() override {
    ParamControl::refresh();
    setButtonsEnabled(toggle.on);
  }

signals:
  void buttonClicked(int id);

protected:
  virtual void onButtonClicked(int id) {
    emit buttonClicked(id);
  }
};

class FrogPilotButtonsControl : public AbstractControl, public FrogPilotButtonGroup {
  Q_OBJECT

public:
  FrogPilotButtonsControl(const QString &title, const QString &desc, const QString &icon,
                          const std::vector<QString> &button_texts, const bool &checkable = false, const bool &exclusive = true,
                          int minimum_button_width = 225) : AbstractControl(title, desc, icon) {
    buildButtons(this, hlayout, button_texts, checkable, exclusive, minimum_button_width);

    QObject::connect(button_group, QOverload<int>::of(&QButtonGroup::buttonClicked), this, &FrogPilotButtonsControl::buttonClicked);
  }

signals:
  void buttonClicked(int id);
};

class FrogPilotButtonToggleControl : public FrogPilotButtonControl {
public:
  FrogPilotButtonToggleControl(const QString &param, const QString &title, const QString &desc, const QString &icon,
                               const std::vector<QString> &button_params, const std::vector<QString> &button_texts,
                               bool exclusive = false, int minimum_button_width = 225)
      : FrogPilotButtonControl(param, title, desc, icon, button_texts, true, exclusive, minimum_button_width), button_params(button_params) {
    for (int id = 0; id < static_cast<int>(button_params.size()); ++id) {
      button_group->button(id)->setChecked(params.getBool(button_params[id].toStdString()));
    }
  }

  void refresh() override {
    FrogPilotButtonControl::refresh();
    for (int id = 0; id < static_cast<int>(button_params.size()); ++id) {
      button_group->button(id)->setChecked(params.getBool(button_params[id].toStdString()));
    }
  }

private:
  void onButtonClicked(int id) override {
    params.putBool(button_params[id].toStdString(), button_group->button(id)->isChecked());
    emit buttonClicked(id);
  }

  std::vector<QString> button_params;
};

class FrogPilotManageControl : public ParamControl {
  Q_OBJECT

public:
  FrogPilotManageControl(const QString &param, const QString &title, const QString &desc, const QString &icon);
  void refresh() override {
    ParamControl::refresh();
    manage_button.setEnabled(toggle.on);
  }

signals:
  void manageButtonClicked();

private:
  QPushButton manage_button;
};

class FrogPilotParamValueControl : public AbstractControl {
  Q_OBJECT

public:
  FrogPilotParamValueControl(const QString &param, const QString &title, const QString &desc, const QString &icon,
                             float min_value, float max_value, const QString &label, const std::map<float, QString> &value_labels = {},
                             float interval = 1.0f, bool fast_increase = false, int label_width = 350);
  virtual void refresh();
  void setWarning(const QString &newWarning);
  void updateControl(const float &newMinValue, const float &newMaxValue, const std::map<float, QString> &newValueLabels = {});
  void updateParam();

signals:
  void valueChanged(float value);

protected:
  QLabel *value_label = nullptr;

  Params params;

private:
  void changeValue(int direction);
  void finishPress(const QPushButton &button);
  void hideEvent(QHideEvent *event) override;
  void showEvent(QShowEvent *event) override;
  void updateDisplay();

  bool fast_increase = false;
  bool hold_accelerated = false;
  bool value_dirty = false;
  bool warning_shown = false;

  float factor = 1.0f;
  float hold_start_value = 0.0f;
  float interval = 1.0f;
  float max_value = 0.0f;
  float min_value = 0.0f;
  float value = 0.0f;

  std::map<float, QString> value_labels;
  std::string key;

  QPushButton decrement_button;
  QPushButton increment_button;

  QString label;
  QString warning;

  QTimer save_timer;
};

class FrogPilotParamValueButtonControl : public FrogPilotParamValueControl {
  Q_OBJECT

public:
  FrogPilotParamValueButtonControl(const QString &param, const QString &title, const QString &desc, const QString &icon,
                                   float min_value, float max_value, const QString &label, const std::map<float, QString> &value_labels,
                                   float interval, bool fast_increase, const std::vector<QString> &button_params,
                                   const std::vector<QString> &button_texts, bool left_button = false, bool checkable = true,
                                   int minimum_button_width = 225)
      : FrogPilotParamValueControl(param, title, desc, icon, min_value, max_value, label, value_labels, interval, fast_increase, 200),
        checkable(checkable), button_params(button_params) {
    button_group = new QButtonGroup(this);
    button_group->setExclusive(false);
    for (int id = 0; id < static_cast<int>(button_texts.size()); ++id) {
      QPushButton *button = new QPushButton(button_texts[id], this);
      button->setCheckable(checkable);
      button->setChecked(checkable && params.getBool(button_params[id].toStdString()));
      button->setStyleSheet(buttonStyle);
      button->setMinimumWidth(minimum_button_width);
      if (left_button) {
        hlayout->insertWidget(hlayout->indexOf(value_label) - 1, button);
      } else {
        hlayout->addWidget(button);
      }
      button_group->addButton(button, id);
    }

    QObject::connect(button_group, QOverload<int>::of(&QButtonGroup::buttonClicked), this, [this](int id) {
      if (this->checkable) {
        params.putBool(this->button_params[id].toStdString(), button_group->button(id)->isChecked());
      }
      emit buttonClicked(id);
    });
  }

  void refresh() override {
    if (checkable) {
      for (int id = 0; id < static_cast<int>(button_params.size()); ++id) {
        button_group->button(id)->setChecked(params.getBool(button_params[id].toStdString()));
      }
    }
    FrogPilotParamValueControl::refresh();
  }

signals:
  void buttonClicked(int id);

private:
  bool checkable = false;

  std::vector<QString> button_params;

  QButtonGroup *button_group = nullptr;
};

class FrogPilotDualParamValueControl : public QFrame {
public:
  FrogPilotDualParamValueControl(FrogPilotParamValueControl *control1, FrogPilotParamValueControl *control2, QWidget *parent = nullptr)
      : QFrame(parent), control1(control1), control2(control2) {
    QHBoxLayout *hlayout = new QHBoxLayout(this);
    hlayout->addWidget(control1);
    hlayout->addWidget(control2);
  }

  void updateControl(const float &newMinValue, const float &newMaxValue, const std::map<float, QString> &newValueLabels = {}) {
    control1->updateControl(newMinValue, newMaxValue, newValueLabels);
    control2->updateControl(newMinValue, newMaxValue, newValueLabels);
  }

private:
  FrogPilotParamValueControl *control1 = nullptr;
  FrogPilotParamValueControl *control2 = nullptr;
};
