"""Native controls for conservative quota and paid-credit preferences."""
from .i18n import tr, display, join_text, format_text, format_value, enum_label
from .localized_widgets import QWidget, QFormLayout, QComboBox, QSpinBox, QCheckBox, set_text
from PySide6.QtWidgets import QVBoxLayout
from .widgets import label

MODES = [('never',tr('Никогда не использовать купленные кредиты')),
         ('confirm',tr('Использовать после подтверждения')),
         ('always',tr('Всегда использовать при наличии'))]


class CreditPolicyEditor(QWidget):
    def __init__(self):
        super().__init__();self.last=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.addWidget(label(tr('Лимиты и купленные кредиты'),'heading'))
        form=QFormLayout();layout.addLayout(form)
        self.mode=QComboBox()
        for value,title in MODES:self.mode.addItem(title,value)
        self.five=QSpinBox();self.week=QSpinBox()
        for widget in (self.five,self.week):widget.setRange(10,100);widget.setSuffix(tr('% осталось'))
        self.ack=QCheckBox(tr('Я осознанно выбираю платное продолжение при поддержке сервиса'))
        form.addRow(tr('Политика'),self.mode);form.addRow(tr('Резерв · 5 часов'),self.five)
        form.addRow(tr('Резерв · неделя'),self.week);form.addRow(self.ack)
        self.mode.currentIndexChanged.connect(self._mode_changed);self._mode_changed()
        layout.addWidget(label(tr('В текущем App Server платное продолжение не поддерживается Mission Control: нет подтверждённого переключателя источника оплаты. Все три режима при пороге ставят новые запросы на паузу. Подтверждение не снимает эту блокировку. Приложение не покупает кредиты и не включает автопополнение.'),'muted'))
        layout.addWidget(label(tr('Резерв не гарантирует отсутствие списаний: начатый запрос может исчерпать квоту. Неизвестные или устаревшие данные блокируют отправку. Активный ход этот экран не останавливает.'),'muted'))

    def _mode_changed(self):
        self.ack.setEnabled(self.mode.currentData()=='always')
        if self.mode.currentData()!='always':self.ack.setChecked(False)

    def value(self):
        return {'mode':self.mode.currentData(),'fiveHourReserve':self.five.value(),
                'weeklyReserve':self.week.value(),'paidAcknowledged':self.ack.isChecked()}

    def update_data(self, value):
        if value==self.last:return
        self.last=dict(value)
        self.mode.setCurrentIndex(max(0,self.mode.findData(value.get('mode','never'))))
        self.five.setValue(value.get('fiveHourReserve',10));self.week.setValue(value.get('weeklyReserve',10))
        self.ack.setChecked(value.get('paidAcknowledged',False))
