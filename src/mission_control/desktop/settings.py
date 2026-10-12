import uuid
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QSpinBox,
    QCheckBox,QListWidget,QFileDialog,QWizard,QWizardPage,QScrollArea)
from .widgets import label,button,row
from .insights import POLICIES


class SettingsPage(QWidget):
    def __init__(self,bridge):
        super().__init__();self.bridge=bridge;self.last=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(label('Настройки','title'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body);form.setSpacing(14)
        scroll.setWidget(body);layout.addWidget(scroll,1)
        from .model_policy import ModelPolicyEditor
        self.model_policies=ModelPolicyEditor()
        from .credit_policy import CreditPolicyEditor
        self.credit_policy=CreditPolicyEditor();form.addRow(self.credit_policy)
        form.addRow(self.model_policies)
        self.codex=QLineEdit();self.auth=label('Нет данных')
        self.roots=QListWidget();self.roots.setMaximumHeight(100)
        self.theme=QComboBox();self.theme.addItems(['dark','light'])
        self.mode=QComboBox();self.mode.addItems(['economy','balanced','quality'])
        self.policy=QComboBox()
        for value,title in POLICIES:self.policy.addItem(title,value)
        self.attempts=QSpinBox();self.attempts.setRange(1,8)
        self.tray=QCheckBox('При закрытии оставаться в трее')
        self.notifications=QCheckBox('Показывать уведомления без текста задания')
        self.reduced_motion=QCheckBox('Уменьшить анимацию интерфейса')
        self.recovery=QCheckBox('При запуске продолжать разрешённую очередь (с сохранением паузы)')
        self.pin=QCheckBox('Оверлей поверх остальных окон');self.codex_only=QCheckBox('Показывать только при активном окне Codex')
        self.hotkey=QLineEdit();self.hotkey.setPlaceholderText('Ctrl+Shift+M')
        for title,widget in [('Codex',row(self.codex,button('Выбрать…',self.pick_codex))),('Авторизация',self.auth),
            ('Рабочие папки',self.roots),('',row(button('Добавить…',self.add_root),button('Удалить',self.remove_root),button('Применить доступ',self.save_roots))),
            ('Тема',self.theme),('Стратегия новых задач',self.mode),('Лимиты новых задач',self.policy),('Максимум попыток',self.attempts),
            ('Закрытие окна',self.tray),('Уведомления',self.notifications),('Анимация',self.reduced_motion),('Восстановление',self.recovery),('Оверлей',self.pin),('',self.codex_only),
            ('Глобальное сочетание',self.hotkey)]:form.addRow(title,widget)
        form.addRow(label('Настройки хранятся в SQLite с Windows DPAPI. Авторизация остаётся в Codex; пароли и токены здесь не запрашиваются. Автозапуск Windows не включается приложением.','muted'))
        form.addRow(label('При неопределённом исходе повтор заблокирован. Новое исполняемое содержимое всегда требует отдельного подтверждения.','muted'))
        from .. import __version__
        form.addRow(label('Mission Control '+__version__+' · локальное приложение, без облачной телеметрии','muted'))
        self.portable_info=label('');form.addRow(self.portable_info)
        self._portable=None
        self.portable_view=button('Просмотреть импортированные данные',self.view_portable);self.portable_view.setEnabled(False);form.addRow(self.portable_view)
        form.addRow('Перенос данных',row(button('Экспорт…',lambda:self.transfer(False)),button('Импорт…',lambda:self.transfer(True))))
        form.addRow('Обновления',button('Проверить файл релиза…',self.check_update))
        layout.addLayout(row(button('Сохранить',self.save,True),button('Проверить подключение',lambda:bridge.request('refresh_connection'))))
    def pick_codex(self):
        path,_=QFileDialog.getOpenFileName(self,'Выберите codex.exe','','Программы (*.exe);;Все файлы (*)')
        if path:self.codex.setText(path)
    def transfer(self,importing):
        from .transfer_dialog import TransferDialog
        from PySide6.QtCore import Qt
        dialog=TransferDialog(self.bridge,importing=importing,parent=self)
        dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.open()
    def check_update(self):
        path,_=QFileDialog.getOpenFileName(self,'Выберите описание релиза','','Release manifest (*.json)')
        if path:self.bridge.request('inspect_update',path=path)
    def view_portable(self):
        if not self._portable:return
        from .transfer_dialog import PortableSummaryDialog
        from PySide6.QtCore import Qt
        dialog=PortableSummaryDialog(self._portable,parent=self);dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.open()
    def add_root(self):
        path=QFileDialog.getExistingDirectory(self,'Разрешённая папка проектов')
        if path and path not in [self.roots.item(i).text() for i in range(self.roots.count())]:self.roots.addItem(path)
    def remove_root(self):self.roots.takeItem(self.roots.currentRow())
    def save_roots(self):
        self.bridge.request('configure_roots',roots=[self.roots.item(i).text() for i in range(self.roots.count())])
    def save(self):
        self.bridge.request('save_preferences',values={'theme':self.theme.currentText(),'codex':self.codex.text(),
            'modelPolicies':self.model_policies.value(),
            'creditPolicy':self.credit_policy.value(),
            'mode':self.mode.currentText(),'policy':self.policy.currentData(),'maxAttempts':self.attempts.value(),
            'closeToTray':self.tray.isChecked(),'notifications':self.notifications.isChecked(),
            'reducedMotion':self.reduced_motion.isChecked(),
            'resumeOnLaunch':self.recovery.isChecked(),'overlayPinned':self.pin.isChecked(),
            'overlayCodexOnly':self.codex_only.isChecked(),'hotkey':self.hotkey.text()})
    def update_data(self,data):
        prefs=data['preferences']
        self.credit_policy.update_data(prefs.get('creditPolicy',{}))
        self.model_policies.update_data(data.get('models',[]),prefs.get('modelPolicies',{}))
        if self.last!=prefs:
            self.last=prefs.copy();self.codex.setText(prefs.get('codex','codex'));self.theme.setCurrentText(prefs.get('theme','dark'))
            self.mode.setCurrentText(prefs.get('mode','balanced'));self.policy.setCurrentIndex(max(0,self.policy.findData(prefs.get('policy','balanced'))))
            self.attempts.setValue(prefs.get('maxAttempts',3));self.tray.setChecked(prefs.get('closeToTray',True))
            self.notifications.setChecked(prefs.get('notifications',True));self.recovery.setChecked(prefs.get('resumeOnLaunch',False))
            self.reduced_motion.setChecked(prefs.get('reducedMotion',False))
            self.pin.setChecked(prefs.get('overlayPinned',True));self.codex_only.setChecked(prefs.get('overlayCodexOnly',False));self.hotkey.setText(prefs.get('hotkey','Ctrl+Shift+M'))
        if getattr(self,'_roots',None)!=data['roots']:
            self._roots=data['roots'].copy();self.roots.clear();self.roots.addItems(data['roots'])
        account=data.get('account',{});self.auth.setText(data['connection']['message']+' · '+str(account.get('planType') or 'Нет данных о плане'))
        portable=data.get('portable')
        self._portable=portable;self.portable_view.setEnabled(bool(portable))
        self.portable_info.setText(('Импортировано справочно: '+str(len(portable['projects']))+' проектов, '+str(len(portable['history']))+' записей. Доступ к папкам задаётся отдельно.') if portable else '')


class SetupWizard(QWizard):
    def __init__(self,bridge,preferences,parent=None):
        super().__init__(parent);self.bridge=bridge;self.setWindowTitle('Первый запуск Mission Control');self.resize(650,440)
        self._pending=None;self._request_token=None
        for key,title in ((QWizard.BackButton,'Назад'),(QWizard.NextButton,'Далее'),
                          (QWizard.FinishButton,'Готово'),(QWizard.CancelButton,'Отмена'),
                          (QWizard.HelpButton,'Справка'),(QWizard.CommitButton,'Применить')):
            self.setButtonText(key,title)
        intro=QWizardPage();intro.setTitle('Управляйте собственными миссиями Codex')
        layout=QVBoxLayout(intro);layout.addWidget(label('Выберите рабочую папку и подключение. Затем создайте задачу, просмотрите её разрешения и запустите очередь. Лимиты и контекст сохраняются между запусками.'))
        layout.addWidget(label('Каждый новый результат с исполняемым кодом ждёт отдельного подтверждения. Полноценной ОС-песочницы нет. Оверлей показывает только миссии этого приложения.'))
        self.addPage(intro)
        connection=QWizardPage();connection.setTitle('Подключение и доступ к проектам');form=QFormLayout(connection)
        self.codex=QLineEdit(preferences.get('codex','codex'));self.root=QLineEdit();self.root.setReadOnly(True)
        form.addRow('Codex',row(self.codex,button('Программа…',self.pick_codex)))
        form.addRow('Рабочая папка',row(self.root,button('Выбрать…',self.pick_root)))
        form.addRow(button('Проверить подключение',self.check));self.status=label('Проверка читает авторизацию, модели и лимиты без запуска задания.');form.addRow(self.status)
        self.bridge.result.connect(self._on_result);self.bridge.stopped.connect(self._backend_stopped);self.addPage(connection)
        self._connection_page=connection
    def pick_codex(self):
        path,_=QFileDialog.getOpenFileName(self,'codex.exe','','Программы (*.exe)')
        if path:self.codex.setText(path)
    def pick_root(self):
        path=QFileDialog.getExistingDirectory(self,'Рабочая папка')
        if path:self.root.setText(path)
    def check(self):
        if self._pending:return
        self._set_pending('probe_connection');self.status.setText('Проверка программы Codex и авторизации…')
        self.bridge.request('probe_connection',codex=self.codex.text().strip(),_request_token=self._request_token)
    def _set_pending(self,action):
        self._pending=action;self._request_token=uuid.uuid4().hex if action else None
        self._connection_page.setEnabled(action is None)
        for key in (QWizard.BackButton,QWizard.FinishButton,QWizard.CancelButton):
            self.button(key).setEnabled(action is None)
    def _on_result(self,action,value):
        if action!=self._pending or value.get('_requestToken')!=self._request_token:return
        self._set_pending(None);self.status.setText(value['message'])
        if action=='complete_setup' and value.get('status')=='connected':super().accept()
    def _backend_stopped(self):
        if self._pending:
            self._set_pending(None);self.status.setText('Backend остановлен. Перезапустите приложение и повторите настройку.')
    def reject(self):
        if not self._pending:super().reject()
    def accept(self):
        if self._pending:return
        if not self.root.text():
            self.status.setText('Рабочая папка: выберите существующую папку проектов.');return
        self._set_pending('complete_setup');self.status.setText('Проверка рабочей папки и подключения Codex…')
        self.bridge.request('complete_setup',codex=self.codex.text().strip(),root=self.root.text(),_request_token=self._request_token)
