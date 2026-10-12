"""Explicit portable data workflow; cryptography runs in the backend worker."""
from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QFileDialog
from .widgets import label, button, row


class TransferDialog(QDialog):
    def __init__(self, bridge, *, importing=False, parent=None):
        super().__init__(parent)
        self.bridge=bridge;self.importing=importing
        self.setWindowTitle('Импорт данных' if importing else 'Экспорт данных')
        self.resize(570,330)
        layout=QFormLayout(self);layout.setSpacing(14)
        layout.addRow(label('Перенос настроек, списка проектов и сводной истории','heading'))
        layout.addRow(label('Задания, сессии, разрешения и исполняемые результаты не переносятся. После импорта потребуется заново настроить подключение и доступ к проектам.'))
        self.path=QLineEdit();self.path.setReadOnly(True);self.path.setAccessibleName('Файл архива')
        layout.addRow('Архив',row(self.path,button('Выбрать…',self.pick)))
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.Password)
        self.password.setMaxLength(1024);self.password.setAccessibleName('Пароль архива')
        layout.addRow('Пароль (от 12 символов)',self.password)
        self.confirm=QLineEdit();self.confirm.setEchoMode(QLineEdit.Password);self.confirm.setMaxLength(1024)
        self.confirm.setAccessibleName('Повтор пароля архива')
        if not importing:layout.addRow('Повторите пароль',self.confirm)
        else:self.confirm.hide()
        layout.addRow(label('Пароль не сохраняется. Без него архив восстановить нельзя. Экспорт создаёт новый файл и не перезаписывает существующий.'))
        self.status=label('');layout.addRow(self.status)
        layout.addRow(row(button('Импортировать' if importing else 'Экспортировать',self.accept,True),button('Отмена',self.reject)))

    def pick(self):
        if self.importing:
            path,_=QFileDialog.getOpenFileName(self,'Открыть защищённый архив','','Mission Control (*.cmc)')
        else:
            path,_=QFileDialog.getSaveFileName(self,'Новый защищённый архив','','Mission Control (*.cmc)')
        if path:self.path.setText(path)

    def accept(self):
        password=self.password.text()
        if not self.path.text():self.status.setText('Выберите файл архива.');return
        if len(password)<12:self.status.setText('Введите пароль длиной от 12 символов.');return
        if not self.importing and password!=self.confirm.text():self.status.setText('Пароли не совпадают.');return
        self.bridge.request('import_portable' if self.importing else 'export_portable',path=self.path.text(),passphrase=password)
        self._clear();super().accept()

    def reject(self):
        self._clear();super().reject()

    def _clear(self):
        self.password.clear();self.confirm.clear()


class PortableSummaryDialog(QDialog):
    """Read-only, plain-text imported records; no project files are opened."""
    def __init__(self, data, parent=None):
        from PySide6.QtWidgets import QVBoxLayout, QTabWidget, QPlainTextEdit
        from ..safety import redact
        super().__init__(parent)
        self.setWindowTitle('Перенесённые проекты и история');self.resize(760,540)
        layout=QVBoxLayout(self)
        layout.addWidget(label('Импортированные записи — только справочная информация. Папки не получают доступ, задания не запускаются.'))
        tabs=QTabWidget();layout.addWidget(tabs,1)
        headings={'name':'Название','path':'Папка','title':'Миссия','status':'Статус','model':'Модель',
                  'effort':'Рассуждения','duration':'Длительность, с','attempts':'Попытки',
                  'completedAt':'Завершение (Unix)','createdAt':'Создание (Unix)'}
        for key,title,fields in [('projects','Проекты',('name','path')),
                                 ('history','История',('title','status','model','effort','duration','attempts','completedAt','createdAt'))]:
            view=QPlainTextEdit();view.setObjectName(key);view.setReadOnly(True);view.setAccessibleName(title)
            collection=data.get(key,[]) if isinstance(data,dict) else []
            if not isinstance(collection,list):collection=[]
            blocks=[]
            for record in collection[:2000]:
                if not isinstance(record,dict):continue
                lines=[headings[field]+': '+redact(str(record[field])[:2048]) for field in fields if field in record]
                if lines:blocks.append('\n'.join(lines))
            view.setPlainText('\n\n'.join(blocks) if blocks else 'Нет перенесённых записей.')
            tabs.addTab(view,title)
        layout.addLayout(row(button('Закрыть',self.accept)))
