from datetime import datetime,timezone
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel,QPlainTextEdit,QPushButton,QFrame,QVBoxLayout,QHBoxLayout


STATUS={'planning':'Оценка задачи','ready':'Маршрут готов','submitted':'Codex выполняет задание','completed_unvalidated':'Результат получен, проверка не завершена','validation_failed':'Проверка не пройдена','attempts_exhausted':'Попытки исчерпаны','limits_unsupported':'Лимиты недоступны','idle':'Нет активной миссии','pending':'Ожидает','running':'Выполняется','paused':'Пауза','completed':'Завершено',
        'failed':'Ошибка проверки','cancelled':'Отменено','waiting_approval':'Нужно подтверждение',
        'needs_attention':'Требуется разбор','waiting_limit':'Ожидание лимита','waiting_credit':'Пауза по кредитной политике','waiting_network':'Нет сети',
        'auth_required':'Требуется вход','waiting_model':'Модель недоступна','waiting_active':'Ожидание Codex'}


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
    widget=QPlainTextEdit();widget.setReadOnly(True);widget.setPlainText(str(text));return widget


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
    for kind,title in [('five_hour','5 часов'),('weekly','Неделя')]:
        windows=[w for w in data.get('windows',[]) if w['kind']==kind]
        if not windows:lines.append(title+': Нет данных');continue
        for w in windows:
            used=w.get('usedPercent');remaining=w.get('remainingPercent')
            value='Нет данных' if used is None or remaining is None else f'{remaining:g}% осталось · {used:g}% использовано'
            reset=w.get('resetsAt')
            when=format_time(reset)
            lines.append(f'{title} [{w["limitId"]}]: {value}\nСброс: {when}')
    return '\n\n'.join(lines)


def format_time(value):
    if value is None:return 'Нет данных'
    try:return datetime.fromtimestamp(value,timezone.utc).astimezone().strftime('%d.%m %H:%M')
    except (ValueError,OverflowError,OSError,TypeError):return 'Нет достоверного времени'


def duration(job,ongoing=False):
    from datetime import datetime
    live=job.get('live',{})
    start=live.get('createdAt')
    end=live.get('updatedAt')
    if not start or not end:return '—'
    try:
        stop=datetime.now(timezone.utc) if ongoing else datetime.fromisoformat(end)
        return f'{max(0,(stop-datetime.fromisoformat(start)).total_seconds()):.0f} с'
    except (ValueError,TypeError):return 'Нет данных'
