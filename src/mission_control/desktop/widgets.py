from .i18n import tr, display, join_text, format_text, format_value, enum_label
from .localized_widgets import QLabel, QPlainTextEdit, QPushButton, set_text
from datetime import datetime,timezone
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout


STATUS={'planning':tr('Оценка задачи'),'ready':tr('Маршрут готов'),'submitted':tr('Codex выполняет задание'),'completed_unvalidated':tr('Результат получен, проверка не завершена'),'validation_failed':tr('Проверка не пройдена'),'attempts_exhausted':tr('Попытки исчерпаны'),'limits_unsupported':tr('Лимиты недоступны'),'idle':tr('Нет активной миссии'),'pending':tr('Ожидает'),'running':tr('Выполняется'),'paused':tr('Пауза'),'completed':tr('Завершено'),
        'failed':tr('Ошибка проверки'),'cancelled':tr('Отменено'),'waiting_approval':tr('Нужно подтверждение'),
        'needs_attention':tr('Требуется разбор'),'waiting_limit':tr('Ожидание лимита'),'waiting_credit':tr('Пауза по кредитной политике'),'waiting_network':tr('Нет сети'),
        'auth_required':tr('Требуется вход'),'waiting_model':tr('Модель недоступна'),'waiting_active':tr('Ожидание Codex'),
        'waiting_resume':tr('Требуется просмотр checkpoint'),'paused_turn':tr('Ход завершён · checkpoint сохранён')}


def label(text='',name=None):
    widget=QLabel(text);widget.setTextFormat(Qt.PlainText);widget.setWordWrap(True)
    if name:widget.setObjectName(name)
    return widget


def button(text,callback,primary=False):
    from .visuals import MotionButton
    widget=MotionButton(text);widget.clicked.connect(callback)
    if primary:widget.setObjectName('primary')
    return widget


def plain(text=''):
    widget=QPlainTextEdit();widget.setReadOnly(True);widget.setPlainText(display(text));return widget


def panel(title):
    frame=QFrame();frame.setObjectName('surface');layout=QVBoxLayout(frame)
    layout.setContentsMargins(20,16,20,16);layout.setSpacing(12)
    layout.addWidget(label(title,'section'));return frame,layout


def row(*widgets):
    layout=QHBoxLayout();layout.setSpacing(8)
    for widget in widgets:layout.addWidget(widget)
    layout.addStretch()
    return layout


def limits_text(data):
    lines=[]
    for kind,title in [('five_hour',tr('5 часов')),('weekly',tr('Неделя'))]:
        windows=[w for w in data.get('windows',[]) if w['kind']==kind]
        if not windows:lines.append(title+tr(': Нет данных'));continue
        for w in windows:
            used=w.get('usedPercent');remaining=w.get('remainingPercent')
            value=tr('Нет данных') if used is None or remaining is None else format_text([format_value(remaining, -1, format_text(['g'])), tr('% осталось · '), format_value(used, -1, format_text(['g'])), tr('% использовано')])
            reset=w.get('resetsAt')
            when=format_time(reset)
            lines.append(format_text([format_value(title, -1, ''), ' [', format_value(w['limitId'], -1, ''), ']: ', format_value(value, -1, ''), tr('\nСброс: '), format_value(when, -1, '')]))
    return join_text('\n\n', lines)


def format_time(value):
    if value is None:return tr('Нет данных')
    try:return datetime.fromtimestamp(value,timezone.utc).astimezone().strftime('%d.%m %H:%M')
    except (ValueError,OverflowError,OSError,TypeError):return tr('Нет достоверного времени')


def duration(job,ongoing=False):
    from datetime import datetime
    live=job.get('live',{})
    start=live.get('createdAt')
    end=live.get('updatedAt')
    if not start or not end:return '—'
    try:
        stop=datetime.now(timezone.utc) if ongoing else datetime.fromisoformat(end)
        return format_text([format_value(max(0, (stop - datetime.fromisoformat(start)).total_seconds()), -1, format_text(['.0f'])), tr(' с')])
    except (ValueError,TypeError):return tr('Нет данных')
