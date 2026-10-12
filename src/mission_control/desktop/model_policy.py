"""Native policy controls sourced from the actual Codex model catalog."""
from copy import deepcopy
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QCheckBox, QComboBox

from .widgets import label, button, row
from ..model_policy import EFFORT_ORDER, OWNER_PROFILE


class ModelPolicyEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.controls = {}
        self._policies = None
        self._catalog = None
        layout = QVBoxLayout(self);layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label('Политика моделей', 'heading'))
        layout.addWidget(label('Предел effort действует во всех режимах, включая Manual и продолжение. '
                               'Переключатель «Автовыбор» влияет только на Router. Уже отправленный ход не отменяется.', 'muted'))
        self.body = QWidget();self.form = QFormLayout(self.body)
        self.form.setContentsMargins(0, 0, 0, 0);self.form.setSpacing(12)
        layout.addWidget(self.body)
        self.status = label('Подключите Codex для получения моделей и уровней рассуждения.', 'muted')
        layout.addWidget(self.status)
        layout.addWidget(button('Профиль: Astra Low · Sol Medium · Luna High', self.apply_profile))

    def value(self):
        result = {}
        for model, (automatic, ceiling, _) in self.controls.items():
            effort = ceiling.currentData()
            if effort is not None or not automatic.isChecked():
                result[model] = {'maxEffort':effort or 'ultra', 'automaticEnabled':automatic.isChecked()}
        return result

    def update_data(self, models, policies):
        if models == self._catalog and policies == self._policies:
            return
        # A metadata refresh must retain edits not yet saved by the user.
        edited = self.value() if policies == self._policies else deepcopy(policies)
        self._policies = deepcopy(policies);self._catalog = deepcopy(models)
        while self.form.rowCount():self.form.removeRow(0)
        self.controls = {}
        ids = list(dict.fromkeys([m['model'] for m in models if isinstance(m.get('model'),str)] + list(edited)))
        for model in ids:
            entries = [m for m in models if m.get('model') == model]
            entry = entries[0] if len(entries) == 1 and not entries[0].get('hidden') else None
            supported = {x.get('reasoningEffort') for x in entry.get('supportedReasoningEfforts', [])} if entry else set()
            automatic = QCheckBox('Автовыбор');automatic.setAccessibleName(model + ' · автовыбор')
            ceiling = QComboBox();ceiling.setAccessibleName(model + ' · максимальный effort')
            ceiling.addItem('Без личного ограничения', None)
            for effort in EFFORT_ORDER:
                if effort in supported:ceiling.addItem(effort.capitalize(), effort)
            rule = edited.get(model)
            automatic.setChecked(rule['automaticEnabled'] if rule else True)
            if rule:
                index = ceiling.findData(rule['maxEffort'])
                if index < 0:
                    ceiling.addItem(rule['maxEffort'].capitalize() + ' (сохранённый предел)', rule['maxEffort'])
                    index = ceiling.count() - 1
                ceiling.setCurrentIndex(index)
            state = label('Доступна' if entry and supported else 'Недоступна · настройка сохранена', 'muted')
            info = QWidget();info_layout = QVBoxLayout(info);info_layout.setContentsMargins(0,0,0,0)
            info_layout.addWidget(label(model));info_layout.addWidget(state)
            self.form.addRow(info, row(automatic, ceiling))
            self.controls[model] = (automatic, ceiling, state)
        self.status.setText('Из Codex получено моделей: ' + str(len(models)) +
                            '. Новые уровни не обходят сохранённый предел. Изменения применяются после «Сохранить».')

    def apply_profile(self):
        ids = [m.get('model') for m in (self._catalog or [])]
        missing = [model for model in OWNER_PROFILE if ids.count(model) != 1]
        if missing:
            self.status.setText('Профиль не применён: отсутствуют или неоднозначны ' + ', '.join(missing))
            return
        edited = {**self.value(), **deepcopy(OWNER_PROFILE)}
        models = self._catalog;original = self._policies
        self._catalog = None;self._policies = None
        self.update_data(models, edited)
        self._policies = original
        self.status.setText('Подготовлен профиль для gpt-6-astra / gpt-6.1-sol / gpt-6-luna. Нажмите «Сохранить».')
