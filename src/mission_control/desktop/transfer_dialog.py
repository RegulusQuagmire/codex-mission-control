"""Explicit portable data workflow; cryptography runs in the backend worker."""
from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text
from .localized_widgets import QDialog, QFormLayout, QLineEdit, QFileDialog, QTabWidget, QPlainTextEdit, set_text

from .widgets import label, button, row, STATUS


class TransferDialog(QDialog):
    def __init__(self, bridge, *, importing=False, parent=None):
        super().__init__(parent)
        self.bridge=bridge;self.importing=importing
        self.setWindowTitle(tr('Импорт данных') if importing else tr('Экспорт данных'))
        self.resize(570,330)
        layout=QFormLayout(self);layout.setSpacing(14)
        layout.addRow(label(tr('Перенос настроек, списка проектов и сводной истории'),'heading'))
        layout.addRow(label(tr('Задания, сессии, разрешения и исполняемые результаты не переносятся. После импорта потребуется заново настроить подключение и доступ к проектам.')))
        self.path=QLineEdit();self.path.setReadOnly(True);self.path.setAccessibleName(tr('Файл архива'))
        layout.addRow(tr('Архив'),row(self.path,button(tr('Выбрать…'),self.pick)))
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.Password)
        self.password.setMaxLength(1024);self.password.setAccessibleName(tr('Пароль архива'))
        layout.addRow(tr('Пароль (от 12 символов)'),self.password)
        self.confirm=QLineEdit();self.confirm.setEchoMode(QLineEdit.Password);self.confirm.setMaxLength(1024)
        self.confirm.setAccessibleName(tr('Повтор пароля архива'))
        if not importing:layout.addRow(tr('Повторите пароль'),self.confirm)
        else:self.confirm.hide()
        layout.addRow(label(tr('Пароль не сохраняется. Без него архив восстановить нельзя. Экспорт создаёт новый файл и не перезаписывает существующий.')))
        self.status=label('');layout.addRow(self.status)
        layout.addRow(row(button(tr('Импортировать') if importing else tr('Экспортировать'),self.accept,True),button(tr('Отмена'),self.reject)))

    def pick(self):
        if self.importing:
            path,_=QFileDialog.getOpenFileName(self,tr('Открыть защищённый архив'),'','Mission Control (*.cmc)')
        else:
            path,_=QFileDialog.getSaveFileName(self,tr('Новый защищённый архив'),'','Mission Control (*.cmc)')
        if path:set_text(self.path, 'setText', path)

    def accept(self):
        password=self.password.text()
        if not self.path.text():set_text(self.status, 'setText', tr('Выберите файл архива.'));return
        if len(password)<12:set_text(self.status, 'setText', tr('Введите пароль длиной от 12 символов.'));return
        if not self.importing and password!=self.confirm.text():set_text(self.status, 'setText', tr('Пароли не совпадают.'));return
        self.bridge.request('import_portable' if self.importing else 'export_portable',path=self.path.text(),passphrase=password)
        self._clear();super().accept()

    def reject(self):
        self._clear();super().reject()

    def _clear(self):
        self.password.clear();self.confirm.clear()


class PortableSummaryDialog(QDialog):
    """Read-only, plain-text imported records; no project files are opened."""
    def __init__(self, data, parent=None):
        from PySide6.QtWidgets import QVBoxLayout
        from ..safety import redact
        super().__init__(parent)
        self.setWindowTitle(tr('Перенесённые проекты и история'));self.resize(760,540)
        layout=QVBoxLayout(self)
        layout.addWidget(label(tr('Импортированные записи — только справочная информация. Папки не получают доступ, задания не запускаются.')))
        tabs=QTabWidget();layout.addWidget(tabs,1)
        headings={'name':tr('Название'),'path':tr('Папка'),'title':tr('Миссия'),'status':tr('Статус'),'model':tr('Модель'),
                  'effort':tr('Рассуждения'),'duration':tr('Длительность, с'),'attempts':tr('Попытки'),
                  'completedAt':tr('Завершение (Unix)'),'createdAt':tr('Создание (Unix)')}
        for key,title,fields in [('projects',tr('Проекты'),('name','path')),
                                 ('history',tr('История'),('title','status','model','effort','duration','attempts','completedAt','createdAt'))]:
            view=QPlainTextEdit();view.setObjectName(key);view.setReadOnly(True);view.setAccessibleName(title)
            collection=data.get(key,[]) if isinstance(data,dict) else []
            if not isinstance(collection,list):collection=[]
            blocks=[]
            for record in collection[:2000]:
                if not isinstance(record,dict):continue
                lines=[]
                for field in fields:
                    if field not in record:continue
                    value=redact(str(record[field])[:2048])
                    if field=='status':value=STATUS.get(value,message_text(value))
                    elif field=='effort':value=enum_label(value)
                    lines.append(headings[field]+': '+value)
                if lines:blocks.append(join_text('\n', lines))
            view.setPlainText(join_text('\n\n', blocks) if blocks else tr('Нет перенесённых записей.'))
            tabs.addTab(view,title)
        layout.addLayout(row(button(tr('Закрыть'),self.accept)))
