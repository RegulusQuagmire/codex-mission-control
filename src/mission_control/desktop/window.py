"""Main native window; all backend operations are asynchronous intents."""
from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text, set_language, manager
from .localized_widgets import QMainWindow, QWidget, QListWidget, QMessageBox, set_text
from PySide6.QtCore import Qt,QTimer,QPropertyAnimation,QEasingCurve
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QStackedWidget, QApplication, QScrollArea, QListView, QGraphicsOpacityEffect, QFrame
from .widgets import label,button,panel,row,limits_text,STATUS,duration
from .theme import apply_theme
from .visuals import MissionBackdrop,RouterNetwork,MotionButton,QuotaTelemetry
from .missions import MissionsPage
from .router import RouterPage
from .approvals import ApprovalsPage,AccessDialog,ResultApprovalDialog,ResultDialog
from .insights import LimitsPage,AnalyticsPage
from .settings import SettingsPage,SetupWizard


class MainWindow(QMainWindow):
    def __init__(self,bridge,*,system_integration=True):
        super().__init__();self.bridge=bridge;self.data={};self.system_integration=system_integration
        self.setWindowTitle('Codex Mission Control');self.resize(1180,780);self.setMinimumSize(800,580)
        central=MissionBackdrop();self.setCentralWidget(central);outer=QVBoxLayout(central)
        outer.setContentsMargins(22,18,22,14);outer.setSpacing(12)
        self.connection=label(tr('Подключение ещё не проверено'),'muted')
        header=QHBoxLayout();header.addWidget(label('MISSION CONTROL','section'));header.addWidget(self.connection,1)
        header.addWidget(button(tr('Подключить Codex'),lambda:self.bridge.request('refresh_connection')))
        header.addWidget(button(tr('Оверлей'),lambda:self.integration.show_overlay() if self.integration else None));outer.addLayout(header)
        self.navigation=QListWidget();self.navigation.setObjectName('navigation')
        self.navigation.setFlow(QListView.LeftToRight);self.navigation.setWrapping(False)
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.navigation.setMaximumHeight(54)
        self.navigation.addItems([tr('Обзор')]);outer.addWidget(self.navigation)
        self.banner=label('','warning');self.banner.hide();outer.addWidget(self.banner)
        self.pages=QStackedWidget();outer.addWidget(self.pages,1)
        self.page_effect=QGraphicsOpacityEffect(self.pages);self.pages.setGraphicsEffect(self.page_effect)
        self.page_animation=QPropertyAnimation(self.page_effect,b'opacity',self)
        self.page_animation.setDuration(200);self.page_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.navigation.currentRowChanged.connect(self.change_page)
        self._dashboard()
        self.missions=MissionsPage(bridge);self.add_page(tr('Миссии'),self.missions)
        self.router=RouterPage(bridge);self.add_page(tr('Маршрутизатор'),self.router)
        self.approvals=ApprovalsPage(bridge);self.add_page(tr('Подтверждения'),self.approvals)
        self.limits=LimitsPage(bridge);self.add_page(tr('Лимиты'),self.limits)
        self.analytics=AnalyticsPage();self.add_page(tr('Аналитика'),self.analytics)
        # Settings already scrolls its form; a second scroll area hides save actions.
        self.settings=SettingsPage(bridge);self.navigation.addItem(tr('Настройки'));self.pages.addWidget(self.settings)
        self._first_snapshot=True
        self.navigation.setCurrentRow(0)
        bridge.snapshot.connect(self.update_snapshot);bridge.error.connect(self.show_error)
        bridge.result.connect(self.on_result)
        apply_theme(QApplication.instance())
        self.integration=None
        if system_integration:
            from .tray import DesktopIntegration
            self.integration=DesktopIntegration(self,bridge)
        self.elapsed_timer=QTimer(self);self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self.render_active)

    def change_page(self,index):
        self.page_animation.stop();self.pages.setCurrentIndex(index)
        if QApplication.instance().property('reducedMotion'):self.page_effect.setOpacity(1.)
        else:
            self.page_animation.setStartValue(.72);self.page_animation.setEndValue(1.);self.page_animation.start()

    def set_reduced_motion(self,value):
        QApplication.instance().setProperty('reducedMotion',bool(value));self.network.set_reduced_motion(value)
        if value:
            self.quota_telemetry.motion.stop();self.quota_telemetry.settle=1.
            self.page_animation.stop();self.page_effect.setOpacity(1.)
            for control in self.findChildren(MotionButton):control.motion.stop();control.hover=0.
        if self.integration:self.integration.overlay.set_reduced_motion(value)

    def _dashboard(self):
        page=QWidget();page.setMinimumSize(710,620)
        layout=QVBoxLayout(page);layout.setContentsMargins(0,4,0,8);layout.setSpacing(14)
        self.run_button=button(tr('Запустить очередь'),lambda:self.bridge.request('start'),True)
        self.pause_button=button(tr('Пауза'),lambda:self.bridge.request('control',action='pause'))
        self.resume_button=button(tr('Продолжить'),self.resume_queue)
        self.stop_button=button(tr('Остановить миссию'),self.stop_active)
        self.result_button=button(tr('Открыть результат'),self.open_active_result)
        body=QHBoxLayout();body.setSpacing(18)
        universe=QWidget();work=QVBoxLayout(universe);work.setContentsMargins(0,0,0,0);work.setSpacing(10)
        work.addLayout(row(label(tr('Сеть решений'),'section'),button(tr('Решения Router'),lambda:self.navigation.setCurrentRow(2))))
        self.network=RouterNetwork();work.addWidget(self.network,1)
        self.network_state=label(tr('Новая задача → оценка → модель → проверка'),'muted');work.addWidget(self.network_state)
        work.addLayout(row(self.run_button,self.pause_button,self.resume_button))
        work.addLayout(row(button(tr('Добавить задачу'),lambda:self.missions.edit()),self.stop_button,self.result_button))
        body.addWidget(universe,1)
        active,content=panel(tr('Активная миссия'));active.setFixedWidth(290);content.setSpacing(8)
        self.mission_title=label(tr('Нет активной миссии'),'missionTitle');content.addWidget(self.mission_title)
        self.active_summary=label(tr('Создайте задание, чтобы начать.'),'muted');content.addWidget(self.active_summary)
        content.addWidget(label(tr('Доступность Codex'),'section'));self.limit_summary=label(tr('5 часов: Нет данных\nНеделя: Нет данных'),'muted');self.limit_summary.hide()
        self.quota_telemetry=QuotaTelemetry();content.addWidget(self.quota_telemetry)
        self.review_hint=label(tr('Новый код ждёт вашего согласия. ОС-песочницы нет.'),'warning')
        content.addWidget(self.review_hint)
        content.addWidget(button(tr('Открыть подтверждения'),lambda:self.navigation.setCurrentRow(3)));content.addStretch()
        body.addWidget(active);layout.addLayout(body,1)
        layout.addLayout(row(label(tr('Далее по маршруту'),'section'),button(tr('Вся очередь'),lambda:self.navigation.setCurrentRow(1))))
        cards=QHBoxLayout();cards.setSpacing(10);self.queue_cards=[]
        for index in range(3):
            card,content=panel(tr('Очередь свободна'));title=content.itemAt(0).widget()
            detail=label(tr('Добавьте новую миссию'),'muted');content.addWidget(detail);cards.addWidget(card,1)
            self.queue_cards.append((title,detail,card))
        layout.addLayout(cards)
        self.next_summary=label(tr('Очередь пуста'),'muted');self.next_summary.hide()
        self._page_shell(page)

    def _page_shell(self,page):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);page.setAutoFillBackground(False);scroll.viewport().setAutoFillBackground(False)
        self.pages.addWidget(scroll)

    def resume_queue(self):
        self.bridge.request('resume_queue')

    def stop_active(self):

        if self.data.get('active') and QMessageBox.question(self,tr('Остановить миссию'),tr('Отменить активное задание? Отправленный запрос может потребовать восстановления.'))==QMessageBox.Yes:
            self.bridge.request('control',action='cancel',identity=self.data['active'])

    def open_active_result(self):
        identity=self.data.get('active')
        if identity is None:
            identity=next((j['id'] for j in reversed(self.data.get('missions',[])) if j.get('runPath')),None)
        if identity:self.bridge.request('result',identity=identity)

    def add_page(self,title,page):
        self.navigation.addItem(title);page.setMinimumSize(700,560);self._page_shell(page)

    def update_snapshot(self,data):
        set_language(data.get('preferences',{}).get('language','ru'))
        self.data=data;set_text(self.connection, 'setText', message_text(data['connection']['message']))
        self.network.set_snapshot(data)
        set_text(self.limit_summary, 'setText', limits_text(data['limits']))
        self.quota_telemetry.set_data(data['limits'],data['preferences'].get('reducedMotion',False))
        jobs=data['missions'];active=next((j for j in jobs if j['id']==data['active']),None)
        self.render_active()
        if active and data['workerRunning']:
            if not self.elapsed_timer.isActive():self.elapsed_timer.start()
        else:self.elapsed_timer.stop()
        pending=sorted((j for j in jobs if j['status']=='pending'),key=lambda j:(-j['priority'],j['sequence']))[:4]
        set_text(self.next_summary, 'setText', join_text('\n', (format_text([format_value(j['title'], -1, ''), tr(' · приоритет '), format_value(j['priority'], -1, ''), ' · ']) + (tr('ожидает ') + join_text(', ', j['dependsOn']) if j['dependsOn'] else tr('готово к запуску')) for j in pending)) or tr('Нет ожидающих заданий'))
        names={job['id']:job['title'] for job in jobs}
        for index,(title,detail,card) in enumerate(self.queue_cards):
            if index<len(pending):
                job=pending[index];set_text(title, 'setText', job['title'])
                set_text(detail, 'setText', tr('Приоритет ') + display(job['priority']) + ' · ' + STATUS.get(job['status'], job['status']) + '\n' + (tr('Ожидает ') + join_text(', ', (names.get(key, key) for key in job['dependsOn'])) if job['dependsOn'] else tr('Готово к запуску')))
            else:set_text(title, 'setText', tr('Свободное место'));set_text(detail, 'setText', tr('Нет следующего задания'))
        running=data['workerRunning'];self.run_button.setEnabled(not running and not data['paused'] and
            (not active or active['status'] not in {'waiting_approval','needs_attention'}))
        self.pause_button.setEnabled(not data['paused'])
        self.stop_button.setEnabled(bool(active and active['status'] not in {'completed','failed','needs_attention','cancelled'}))
        self.result_button.setEnabled(any(j.get('runPath') for j in jobs))
        self.resume_button.setEnabled(data['paused'] and (not active or
            active['status'] not in {'waiting_approval','needs_attention'} or active.get('executionApproved',False)))
        theme=data['preferences'].get('theme','dark')
        if getattr(self,'_theme',None)!=theme:apply_theme(QApplication.instance(),theme);self._theme=theme
        self.set_reduced_motion(data['preferences'].get('reducedMotion',False))
        self.missions.update_data(data)
        self.router.update_data(data)
        self.approvals.update_data(data)
        self.limits.update_data(data);self.analytics.update_data(data);self.settings.update_data(data)
        if self.integration:self.integration.update_data(data)
        if self._first_snapshot and self.system_integration:
            self._first_snapshot=False
            if not data['preferences'].get('setupComplete'):
                wizard=SetupWizard(self.bridge,data['preferences'],self);wizard.setAttribute(Qt.WA_DeleteOnClose);wizard.open()
            elif data['preferences'].get('resumeOnLaunch') and not data['paused']:
                self.bridge.request('start')

    def render_active(self):
        data=self.data
        active=next((j for j in data.get('missions',[]) if j['id']==data.get('active')),None)
        if active:
            live=active.get('live',{});decision=live.get('decision') or active.get('model') or {}
            state=live.get('stage') or active['status']
            set_text(self.mission_title, 'setText', active['title'])
            set_text(self.network_state, 'setText', STATUS.get(state, state) + ' · ' + decision.get('model', tr('Модель не выбрана')) + ' / ' + enum_label(decision.get('effort','—')))
            from pathlib import Path
            reason=message_text(decision.get('reason',''));wait=message_text(live.get('waitReason') or live.get('stopReason') or '')
            shorten=lambda value,maximum:value if len(value)<=maximum else value[:maximum-1]+'…'
            project=active['project'];project_name=Path(project).name or project
            self.active_summary.setToolTip(project+'\n'+reason+'\n'+wait)
            set_text(self.active_summary, 'setText', join_text('\n', filter(None, [project_name, STATUS.get(state, state) + ' · ' + duration(active, data.get('workerRunning', False)), decision.get('model', tr('Модель ещё не выбрана')) + ' / ' + enum_label(decision.get('effort','—')), shorten(reason, 90), shorten(wait, 90)])))
        else:
            set_text(self.mission_title, 'setText', tr('Нет активной миссии'));set_text(self.active_summary, 'setText', tr('Выберите проект и создайте задание.'));set_text(self.network_state, 'setText', tr('Новая задача → оценка → модель → проверка'))

    def show_error(self,message):set_text(self.banner, 'setText', tr('Ошибка: ') + message_text(message));self.banner.show()
    def on_result(self,action,result):
        if action in {'export_portable','import_portable'}:
            set_text(self.banner, 'setText', message_text(result['message']));self.banner.show()
        if action=='inspect_update':

            message=(tr('Доступна новая версия ') if result['newer'] else tr('Более новой версии нет: '))+result['version']
            message+='\n'+result['notes']+tr('\n\nИсточник файла не подтверждён. Проверьте издателя и подпись установщика. Автоматическая установка отключена.')
            QMessageBox.information(self,tr('Проверка версии'),message)
        if action in {'access_review','review_result','result'}:
            cls={'access_review':AccessDialog,'review_result':ResultApprovalDialog,'result':ResultDialog}[action]
            dialog=cls(result,self.bridge,self);dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.open()
        if action=='approve_result' and not self.data.get('paused'):self.bridge.request('start')

    def closeEvent(self,event):
        if self.integration and not self.integration.closing:
            from PySide6.QtWidgets import QSystemTrayIcon
            event.ignore()
            if self.data.get('preferences',{}).get('closeToTray',True) and QSystemTrayIcon.isSystemTrayAvailable():self.hide()
            else:self.integration.exit()
            return
        self.page_animation.stop();self.network.pulse.stop();self.quota_telemetry.motion.stop();self.elapsed_timer.stop()
        for control in self.findChildren(MotionButton):control.motion.stop()
        event.accept()
