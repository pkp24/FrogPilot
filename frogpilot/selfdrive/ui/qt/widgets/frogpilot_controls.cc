#include "frogpilot/selfdrive/ui/qt/widgets/frogpilot_controls.h"

#include <algorithm>
#include <cmath>

#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>

const QString buttonStyle = R"(
  QPushButton {
    padding: 0px 25px 0px 25px;
    border-radius: 50px;
    font-size: 35px;
    font-weight: 500;
    height: 100px;
    color: #E4E4E4;
    background-color: #393939;
  }
  QPushButton:pressed {
    background-color: #4a4a4a;
  }
  QPushButton:checked:enabled {
    background-color: #33Ab4C;
  }
  QPushButton:disabled {
    color: #33E4E4E4;
  }
)";

bool FrogPilotConfirmationDialog::toggleReboot(QWidget *parent) {
  ConfirmationDialog dialog(tr("Reboot required to take effect."), tr("Reboot Now"), tr("Reboot Later"), false, parent);
  if (dialog.exec() != QDialog::Accepted) {
    return false;
  }

  for (FrogPilotParamValueControl *control : parent->findChildren<FrogPilotParamValueControl*>()) {
    if (control->isVisible()) {
      control->updateParam();
    }
  }
  return true;
}

bool FrogPilotConfirmationDialog::yesorno(const QString &prompt_text, QWidget *parent) {
  ConfirmationDialog dialog(prompt_text, tr("Yes"), tr("No"), false, parent);
  return dialog.exec() == QDialog::Accepted;
}

FrogPilotManageControl::FrogPilotManageControl(const QString &param, const QString &title, const QString &desc, const QString &icon)
    : ParamControl(param, title, desc, icon), manage_button(tr("MANAGE"), this) {
  manage_button.setFixedSize(250, 100);
  manage_button.setStyleSheet(buttonStyle);
  hlayout->insertWidget(hlayout->indexOf(&toggle), &manage_button);
  QObject::connect(&manage_button, &QPushButton::clicked, this, &FrogPilotManageControl::manageButtonClicked);
  QObject::connect(this, &ToggleControl::toggleFlipped, this, &FrogPilotManageControl::refresh);
}

FrogPilotParamValueControl::FrogPilotParamValueControl(const QString &param, const QString &title, const QString &desc, const QString &icon,
                                                     float min_value, float max_value, const QString &label,
                                                     const std::map<float, QString> &value_labels, float interval, bool fast_increase, int label_width)
    : AbstractControl(title, desc, icon), fast_increase(fast_increase), factor(std::pow(10, std::ceil(-std::log10(interval)))),
      interval(interval), max_value(max_value), min_value(min_value),
      value_labels(value_labels), key(param.toStdString()), label(label) {
  value_label = new QLabel(this);
  value_label->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
  value_label->setFixedSize(label_width, 100);
  value_label->setStyleSheet("QLabel {color: #E0E879;}");
  hlayout->addWidget(value_label);

  const QString value_button_style = buttonStyle + " QPushButton { font-size: 50px; }";
  decrement_button.setText("-");
  increment_button.setText("+");
  for (QPushButton *button : {&decrement_button, &increment_button}) {
    button->setFixedSize(150, 100);
    button->setStyleSheet(value_button_style);
    button->setAutoRepeat(true);
    button->setAutoRepeatDelay(500);
    button->setAutoRepeatInterval(150);
    hlayout->addWidget(button);
    QObject::connect(button, &QPushButton::released, this, [this, button]() { finishPress(*button); });
  }
  QObject::connect(&decrement_button, &QPushButton::pressed, this, [this]() { changeValue(-1); });
  QObject::connect(&increment_button, &QPushButton::pressed, this, [this]() { changeValue(1); });

  save_timer.setSingleShot(true);
  save_timer.setInterval(150);
  QObject::connect(&save_timer, &QTimer::timeout, this, &FrogPilotParamValueControl::updateParam);
}

void FrogPilotParamValueControl::changeValue(int direction) {
  save_timer.stop();
  if (!warning.isEmpty() && !warning_shown) {
    warning_shown = true;
    decrement_button.setDown(false);
    increment_button.setDown(false);
    ConfirmationDialog::alert(warning, this);
    return;
  }

  float step = interval;
  if (fast_increase && hold_accelerated) {
    step *= 5;
  }
  value = std::clamp(value + direction * step, min_value, max_value);
  value = std::clamp(std::round(value * factor) / factor, min_value, max_value);
  value_dirty = true;

  if (std::abs(value - hold_start_value) > 5 * interval && std::lround(value / interval) % 5 == 0) {
    hold_accelerated = true;
  }

  emit valueChanged(value);
  updateDisplay();
}

void FrogPilotParamValueControl::finishPress(const QPushButton &button) {
  // Qt emits released during auto-repeat while the button remains down.
  if (button.isDown()) {
    return;
  }

  hold_accelerated = false;
  hold_start_value = value;
  if (!decrement_button.isDown() && !increment_button.isDown() && value_dirty) {
    save_timer.start();
  }
}

void FrogPilotParamValueControl::refresh() {
  save_timer.stop();
  const float stored_value = std::round(params.getFloat(key) * factor) / factor;
  value = std::clamp(stored_value, min_value, max_value);
  value_dirty = value != stored_value;
  hold_accelerated = false;
  hold_start_value = value;
  updateDisplay();
}

void FrogPilotParamValueControl::setWarning(const QString &newWarning) {
  warning = newWarning;
}

void FrogPilotParamValueControl::updateControl(const float &newMinValue, const float &newMaxValue,
                                              const std::map<float, QString> &newValueLabels) {
  min_value = newMinValue;
  max_value = newMaxValue;
  value_labels = newValueLabels;
  refresh();
}

void FrogPilotParamValueControl::updateParam() {
  save_timer.stop();
  if (value_dirty) {
    params.putFloat(key, value);
    value_dirty = false;
  }
}

void FrogPilotParamValueControl::hideEvent(QHideEvent *event) {
  AbstractControl::hideEvent(event);
  decrement_button.setDown(false);
  increment_button.setDown(false);
  hold_accelerated = false;
  hold_start_value = value;
  warning_shown = false;
  updateParam();
}

void FrogPilotParamValueControl::showEvent(QShowEvent *event) {
  refresh();
}

void FrogPilotParamValueControl::updateDisplay() {
  QString text = QString::number(value) + label;
  for (const std::pair<const float, QString> &entry : value_labels) {
    if (std::lround(entry.first * factor) == std::lround(value * factor)) {
      text = entry.second;
      break;
    }
  }
  value_label->setText(text);
}

bool useKonikServer() {
  static const bool use_konik = QFile::exists("/cache/use_konik");
  return use_konik;
}

void clearMovie(QSharedPointer<QMovie> &movie, QWidget *parent) {
  if (movie) {
    movie->stop();
    QObject::disconnect(movie.data(), nullptr, parent, nullptr);
    movie.reset();
  }
}

void loadGif(const QString &gifPath, QSharedPointer<QMovie> &movie, const QSize &size, QWidget *parent, bool repaintOnFrame) {
  if (!parent) {
    return;
  }

  const QFileInfo source(gifPath);
  if (gifPath.isEmpty() || !source.exists()) {
    clearMovie(movie, parent);
    return;
  }

  QString source_path = source.canonicalFilePath();
  if (source_path.isEmpty()) {
    source_path = source.absoluteFilePath();
  }
  if (!movie || movie->fileName() != source_path) {
    clearMovie(movie, parent);
    movie = QSharedPointer<QMovie>::create(source_path);
    movie->setCacheMode(QMovie::CacheAll);
    if (repaintOnFrame) {
      QObject::connect(movie.data(), &QMovie::frameChanged, parent, [parent]() {
        if (parent->isVisible()) {
          parent->update();
        }
      });
    }
  }

  movie->setScaledSize(size);
  movie->start();
}

void loadImage(const QString &basePath, QPixmap &pixmap, QSharedPointer<QMovie> &movie, const QSize &size, QWidget *parent) {
  if (!parent) {
    return;
  }

  pixmap = QPixmap();
  const QString gif_path = basePath + ".gif";
  if (QFileInfo::exists(gif_path)) {
    loadGif(gif_path, movie, size, parent);
  } else {
    clearMovie(movie, parent);
    const QPixmap image(QFileInfo(basePath + ".png").canonicalFilePath());
    if (!image.isNull()) {
      pixmap = image.scaled(size, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    }
  }
  parent->update();
}

void updateFrogPilotToggles() {
  static Params params_memory{"/dev/shm/params"};
  params_memory.putBool("FrogPilotTogglesUpdated", true);
}

QColor loadThemeColors(const QString &colorKey, bool clearCache) {
  static QJsonObject colors;
  if (clearCache) {
    colors = QJsonObject();
    QFile file("../../frogpilot/selfdrive/assets/active_theme/colors/colors.json");
    if (file.open(QIODevice::ReadOnly)) {
      colors = QJsonDocument::fromJson(file.readAll()).object();
    }
  }
  if (colors.isEmpty()) {
    return QColor();
  }

  QColor color(255, 255, 255);
  if (!colorKey.isEmpty()) {
    const QJsonObject components = colors.value(colorKey).toObject();
    color.setRgb(components.value("red").toInt(255), components.value("green").toInt(255),
                 components.value("blue").toInt(255), components.value("alpha").toInt(255));
  }
  return color;
}

QString processModelName(const QString &modelName) {
  static const QRegularExpression model_icons("[🗺️👀📡]");
  QString name = modelName;
  name.remove(model_icons);
  name.remove("(Default)");
  return name.simplified();
}
