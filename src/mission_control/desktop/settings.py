from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text, set_language, manager
from .localized_widgets import QWidget, QFormLayout, QLineEdit, QComboBox, QSpinBox, QCheckBox, QListWidget, QFileDialog, QWizard, QWizardPage, set_text
import uuid
from PySide6.QtWidgets import QVBoxLayout, QScrollArea
from .widgets import label,button,row
from .insights import POLICIES


class SettingsPage(QWidget):
    def __init__(self,bridge):
        super().__init__();self.bridge=bridge;self.last=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(label(tr('Настройки'),'title'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body);form.setSpacing(14)
        scroll.setWidget(body);layout.addWidget(scroll,1)
        self.language=QComboBox();self.language.addItem('Русский','ru');self.language.addItem('English','en')
        self.language.setAccessibleName(tr('Язык интерфейса'))
        form.addRow(tr('Язык интерфейса'),self.language)
        self.language.currentIndexChanged.connect(self.change_language)
        manager.changed.connect(self.sync_language)
        from .model_policy import ModelPolicyEditor
        self.model_policies=ModelPolicyEditor()
        from .credit_policy import CreditPolicyEditor
        self.credit_policy=CreditPolicyEditor();form.addRow(self.credit_policy)
        form.addRow(self.model_policies)
        self.codex=QLineEdit();self.auth=label(tr('Нет данных'))
        self.roots=QListWidget();self.roots.setMaximumHeight(100)
        self.theme=QComboBox();self.theme.addEnums(['dark','light'])
        self.mode=QComboBox();self.mode.addEnums(['economy','balanced','quality'])
        self.policy=QComboBox()
        for value,title in POLICIES:self.policy.addItem(title,value)
        self.attempts=QSpinBox();self.attempts.setRange(1,8)
        self.tray=QCheckBox(tr('При закрытии оставаться в трее'))
        self.notifications=QCheckBox(tr('Показывать уведомления без текста задания'))
        self.reduced_motion=QCheckBox(tr('Уменьшить анимацию интерфейса'))
        self.recovery=QCheckBox(tr('При запуске продолжать разрешённую очередь (с сохранением паузы)'))
        self.pin=QCheckBox(tr('Оверлей поверх остальных окон'));self.codex_only=QCheckBox(tr('Показывать только при активном окне Codex'))
        self.hotkey=QLineEdit();self.hotkey.setPlaceholderText('Ctrl+Shift+M')
        for title,widget in [('Codex',row(self.codex,button(tr('Выбрать…'),self.pick_codex))),(tr('Авторизация'),self.auth),
            (tr('Рабочие папки'),self.roots),('',row(button(tr('Добавить…'),self.add_root),button(tr('Удалить'),self.remove_root),button(tr('Применить доступ'),self.save_roots))),
            (tr('Тема'),self.theme),(tr('Стратегия новых задач'),self.mode),(tr('Лимиты новых задач'),self.policy),(tr('Максимум попыток'),self.attempts),
            (tr('Закрытие окна'),self.tray),(tr('Уведомления'),self.notifications),(tr('Анимация'),self.reduced_motion),(tr('Восстановление'),self.recovery),(tr('Оверлей'),self.pin),('',self.codex_only),
            (tr('Глобальное сочетание'),self.hotkey)]:form.addRow(title,widget)
        form.addRow(label(tr('Настройки хранятся в SQLite с Windows DPAPI. Авторизация остаётся в Codex; пароли и токены здесь не запрашиваются. Автозапуск Windows не включается приложением.'),'muted'))
        form.addRow(label(tr('При неопределённом исходе повтор заблокирован. Новое исполняемое содержимое всегда требует отдельного подтверждения.'),'muted'))
        from .. import __version__
        form.addRow(label('Mission Control '+__version__+tr(' · локальное приложение, без облачной телеметрии'),'muted'))
        self.portable_info=label('');form.addRow(self.portable_info)
        self._portable=None
        self.portable_view=button(tr('Просмотреть импортированные данные'),self.view_portable);self.portable_view.setEnabled(False);form.addRow(self.portable_view)
        form.addRow(tr('Перенос данных'),row(button(tr('Экспорт…'),lambda:self.transfer(False)),button(tr('Импорт…'),lambda:self.transfer(True))))
        form.addRow(tr('Обновления'),button(tr('Проверить файл релиза…'),self.check_update))
        layout.addLayout(row(button(tr('Сохранить'),self.save,True),button(tr('Проверить подключение'),lambda:bridge.request('refresh_connection'))))
    def pick_codex(self):
        path,_=QFileDialog.getOpenFileName(self,tr('Выберите codex.exe'),'',tr('Программы (*.exe);;Все файлы (*)'))
        if path:set_text(self.codex, 'setText', path)
    def change_language(self):
        value=self.language.currentData()
        if value:
            set_language(value)
            self.bridge.request('save_preferences',values={'language':value})
    def sync_language(self, value):
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(self.language):self.language.selectData(value)
    def transfer(self,importing):
        from .transfer_dialog import TransferDialog
        from PySide6.QtCore import Qt
        dialog=TransferDialog(self.bridge,importing=importing,parent=self)
        dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.open()
    def check_update(self):
        path,_=QFileDialog.getOpenFileName(self,tr('Выберите описание релиза'),'',tr('Описание релиза (*.json)'))
        if path:self.bridge.request('inspect_update',path=path)
    def view_portable(self):
        if not self._portable:return
        from .transfer_dialog import PortableSummaryDialog
        from PySide6.QtCore import Qt
        dialog=PortableSummaryDialog(self._portable,parent=self);dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.open()
    def add_root(self):
        path=QFileDialog.getExistingDirectory(self,tr('Разрешённая папка проектов'))
        if path and path not in [self.roots.item(i).text() for i in range(self.roots.count())]:self.roots.addItem(path)
    def remove_root(self):self.roots.takeItem(self.roots.currentRow())
    def save_roots(self):
        self.bridge.request('configure_roots',roots=[self.roots.item(i).text() for i in range(self.roots.count())])
    def save(self):
        self.bridge.request('save_preferences',values={'language':self.language.currentData(),'theme':self.theme.currentData(),'codex':self.codex.text(),
            'modelPolicies':self.model_policies.value(),
            'creditPolicy':self.credit_policy.value(),
            'mode':self.mode.currentData(),'policy':self.policy.currentData(),'maxAttempts':self.attempts.value(),
            'closeToTray':self.tray.isChecked(),'notifications':self.notifications.isChecked(),
            'reducedMotion':self.reduced_motion.isChecked(),
            'resumeOnLaunch':self.recovery.isChecked(),'overlayPinned':self.pin.isChecked(),
            'overlayCodexOnly':self.codex_only.isChecked(),'hotkey':self.hotkey.text()})
    def update_data(self,data):
        prefs=data['preferences']
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(self.language):self.language.selectData(prefs.get('language','ru'))
        self.credit_policy.update_data(prefs.get('creditPolicy',{}))
        self.model_policies.update_data(data.get('models',[]),prefs.get('modelPolicies',{}))
        prior={k:v for k,v in (self.last or {}).items() if k!='language'}
        current={k:v for k,v in prefs.items() if k!='language'}
        self.last=prefs.copy()
        if prior!=current:
            self.last=prefs.copy();set_text(self.codex, 'setText', prefs.get('codex', 'codex'));self.theme.selectData(prefs.get('theme','dark'))
            self.mode.selectData(prefs.get('mode','balanced'));self.policy.setCurrentIndex(max(0,self.policy.findData(prefs.get('policy','balanced'))))
            self.attempts.setValue(prefs.get('maxAttempts',3));self.tray.setChecked(prefs.get('closeToTray',True))
            self.notifications.setChecked(prefs.get('notifications',True));self.recovery.setChecked(prefs.get('resumeOnLaunch',False))
            self.reduced_motion.setChecked(prefs.get('reducedMotion',False))
            self.pin.setChecked(prefs.get('overlayPinned',True));self.codex_only.setChecked(prefs.get('overlayCodexOnly',False));set_text(self.hotkey, 'setText', prefs.get('hotkey', 'Ctrl+Shift+M'))
        if getattr(self,'_roots',None)!=data['roots']:
            self._roots=data['roots'].copy();self.roots.clear();self.roots.addItems(data['roots'])
        account=data.get('account',{});set_text(self.auth, 'setText', message_text(data['connection']['message']) + ' · ' + display(account.get('planType') or tr('Нет данных о плане')))
        portable=data.get('portable')
        self._portable=portable;self.portable_view.setEnabled(bool(portable))
        set_text(self.portable_info, 'setText', tr('Импортировано справочно: ') + display(len(portable['projects'])) + tr(' проектов, ') + display(len(portable['history'])) + tr(' записей. Доступ к папкам задаётся отдельно.') if portable else '')


class SetupWizard(QWizard):
    def __init__(self,bridge,preferences,parent=None):
        super().__init__(parent);self.bridge=bridge;self.setWindowTitle(tr('Первый запуск Mission Control'));self.resize(650,440)
        self._pending=None;self._request_token=None
        from .i18n import language
        self.language=QComboBox();self.language.addItem('Русский','ru');self.language.addItem('English','en')
        self.language.selectData(language());self.language.setAccessibleName(tr('Язык интерфейса'))
        self.language.currentIndexChanged.connect(self.change_language)
        manager.changed.connect(self.sync_language)
        for key,title in ((QWizard.BackButton,tr('Назад')),(QWizard.NextButton,tr('Далее')),
                          (QWizard.FinishButton,tr('Готово')),(QWizard.CancelButton,tr('Отмена')),
                          (QWizard.HelpButton,tr('Справка')),(QWizard.CommitButton,tr('Применить'))):
            self.setButtonText(key,title)
        intro=QWizardPage();intro.setTitle(tr('Управляйте собственными миссиями Codex'))
        layout=QVBoxLayout(intro);layout.addWidget(label(tr('Выберите рабочую папку и подключение. Затем создайте задачу, просмотрите её разрешения и запустите очередь. Лимиты и контекст сохраняются между запусками.')))
        layout.addWidget(label(tr('Язык интерфейса')));layout.addWidget(self.language)
        layout.addWidget(label(tr('Каждый новый результат с исполняемым кодом ждёт отдельного подтверждения. Полноценной ОС-песочницы нет. Оверлей показывает только миссии этого приложения.')))
        self.addPage(intro)
        connection=QWizardPage();connection.setTitle(tr('Подключение и доступ к проектам'));form=QFormLayout(connection)
        self.codex=QLineEdit(preferences.get('codex','codex'));self.root=QLineEdit();self.root.setReadOnly(True)
        form.addRow('Codex',row(self.codex,button(tr('Программа…'),self.pick_codex)))
        form.addRow(tr('Рабочая папка'),row(self.root,button(tr('Выбрать…'),self.pick_root)))
        form.addRow(button(tr('Проверить подключение'),self.check));self.status=label(tr('Проверка читает авторизацию, модели и лимиты без запуска задания.'));form.addRow(self.status)
        self.bridge.result.connect(self._on_result);self.bridge.stopped.connect(self._backend_stopped);self.addPage(connection)
        self._connection_page=connection
    def change_language(self):
        value=self.language.currentData()
        set_language(value);self.bridge.request('save_preferences',values={'language':value})
    def sync_language(self, value):
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(self.language):self.language.selectData(value)
    def pick_codex(self):
        path,_=QFileDialog.getOpenFileName(self,'codex.exe','',tr('Программы (*.exe)'))
        if path:set_text(self.codex, 'setText', path)
    def pick_root(self):
        path=QFileDialog.getExistingDirectory(self,tr('Рабочая папка'))
        if path:set_text(self.root, 'setText', path)
    def check(self):
        if self._pending:return
        self._set_pending('probe_connection');set_text(self.status, 'setText', tr('Проверка программы Codex и авторизации…'))
        self.bridge.request('probe_connection',codex=self.codex.text().strip(),_request_token=self._request_token)
    def _set_pending(self,action):
        self._pending=action;self._request_token=uuid.uuid4().hex if action else None
        self._connection_page.setEnabled(action is None)
        for key in (QWizard.BackButton,QWizard.FinishButton,QWizard.CancelButton):
            self.button(key).setEnabled(action is None)
    def _on_result(self,action,value):
        if action!=self._pending or value.get('_requestToken')!=self._request_token:return
        self._set_pending(None);set_text(self.status, 'setText', message_text(value['message']))
        if action=='complete_setup' and value.get('status')=='connected':super().accept()
    def _backend_stopped(self):
        if self._pending:
            self._set_pending(None);set_text(self.status, 'setText', tr('Backend остановлен. Перезапустите приложение и повторите настройку.'))
    def reject(self):
        if not self._pending:super().reject()
    def accept(self):
        if self._pending:return
        if not self.root.text():
            set_text(self.status, 'setText', tr('Рабочая папка: выберите существующую папку проектов.'));return
        self._set_pending('complete_setup');set_text(self.status, 'setText', tr('Проверка рабочей папки и подключения Codex…'))
        self.bridge.request('complete_setup',codex=self.codex.text().strip(),root=self.root.text(),_request_token=self._request_token)
