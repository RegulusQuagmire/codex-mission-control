from PySide6.QtWidgets import QSystemTrayIcon,QMenu,QApplication,QStyle,QMessageBox
from .overlay import MissionOverlay
from .windows import WindowsIntegration


class DesktopIntegration:
    def __init__(self,window,bridge):
        self.window=window;self.bridge=bridge;self.closing=False;self.desired=False;self.foreground=False
        self.overlay=MissionOverlay(bridge,self.open_active);self.previous={};self._waiting=False
        self.overlay.hide_requested.connect(self.hide_overlay)
        self.overlay.preferences_changed.connect(lambda values:bridge.request('save_preferences',values=values))
        self._overlay_restored=False
        self.native=WindowsIntegration(QApplication.instance());self.native.activated.connect(self.toggle_overlay)
        self.native.foreground_changed.connect(self.on_foreground);self.native.warning.connect(window.show_error)
        self.tray=QSystemTrayIcon(window.style().standardIcon(QStyle.SP_ComputerIcon),window)
        self.tray.setToolTip('Codex Mission Control');menu=QMenu(window)
        menu.addAction('Открыть Mission Control',self.show_main);self.status=menu.addAction('Готово');self.status.setEnabled(False)
        self.pause_action=menu.addAction('Пауза очереди',lambda:bridge.request('control',action='pause'))
        self.resume_action=menu.addAction('Продолжить',window.resume_queue)
        menu.addSeparator();menu.addAction('Показать оверлей',self.show_overlay);menu.addAction('Скрыть оверлей',self.hide_overlay)
        menu.addSeparator();menu.addAction('Полный выход',self.exit)
        self.tray.setContextMenu(menu);self.tray.activated.connect(lambda reason:self.show_main() if reason==QSystemTrayIcon.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():self.tray.show()
        bridge.stopped.connect(self.finished)
    def show_main(self):self.window.showNormal();self.window.raise_();self.window.activateWindow()
    def open_active(self):
        self.show_main();self.window.navigation.setCurrentRow(1)
        active=self.window.data.get('active')
        for i,job in enumerate(self.window.missions.jobs):
            if job['id']==active:self.window.missions.table.selectRow(i);break
    def toggle_overlay(self):
        if self.desired:self.hide_overlay()
        else:self.show_overlay()
    def show_overlay(self):
        self.desired=True
        prefs=self.window.data.get('preferences',{})
        if prefs.get('overlayCodexOnly') and self.native.monitoring:
            self.foreground=self.native.is_codex_foreground();self.on_foreground(self.foreground)
        else:self.overlay.show()
    def hide_overlay(self):self.desired=False;self.overlay.hide()
    def on_foreground(self,value):
        self.foreground=value
        only=self.window.data.get('preferences',{}).get('overlayCodexOnly',False)
        self.overlay.setVisible(self.desired and (not only or value or not self.native.monitoring))
    def update_data(self,data):
        self.overlay.update_data(data);prefs=data['preferences']
        if not self._overlay_restored:
            self._overlay_restored=True
            if prefs.get('overlayX') is not None and prefs.get('overlayY') is not None:
                from PySide6.QtCore import QPoint
                point=QPoint(prefs['overlayX'],prefs['overlayY'])
                screens=QApplication.screens()
                screen=next((s for s in screens if s.availableGeometry().contains(point)),QApplication.primaryScreen())
                bounds=screen.availableGeometry()
                self.overlay.move(max(bounds.left(),min(point.x(),bounds.right()-self.overlay.width())),
                    max(bounds.top(),min(point.y(),bounds.bottom()-self.overlay.height())))
            if prefs.get('overlayCompact'):
                self.overlay.compact=True;self.overlay.details.hide();self.overlay.adjustSize()
        self.native.set_hotkey(prefs.get('hotkey','Ctrl+Shift+M'))
        self.native.set_monitoring(bool(prefs.get('overlayCodexOnly')))
        self.on_foreground(self.foreground)
        self.pause_action.setEnabled(not data['paused']);self.resume_action.setEnabled(self.window.resume_button.isEnabled())
        active=next((j for j in data['missions'] if j['id']==data['active']),None)
        state='Пауза' if data['paused'] else (active['status'] if active else 'Готово')
        self.status.setText(state);self.tray.setToolTip('Mission Control · '+state)
        if prefs.get('notifications',True):
            for job in data['missions']:
                prior=self.previous.get(job['id']);status=job.get('live',{}).get('stage') or job['status']
                messages={'completed':'Задание завершено. Результат доступен в приложении.',
                    'waiting_approval':'Требуется просмотр и подтверждение результата.',
                    'waiting_limit':'Работа ожидает восстановления лимита.',
                    'needs_attention':'Требуется ручной разбор состояния.', 'failed':'Проверка задания завершилась ошибкой.'}
                if prior is not None and prior!=status:
                    if status in messages:self.tray.showMessage('Mission Control',messages[status],QSystemTrayIcon.Information,8000)
                    elif prior=='waiting_limit' and status=='running':self.tray.showMessage('Mission Control','Доступность восстановлена; работа продолжается.',QSystemTrayIcon.Information,6000)
        self.previous={j['id']:j.get('live',{}).get('stage') or j['status'] for j in data['missions']}
    def exit(self):
        if self.closing:return
        if self.window.data.get('workerRunning'):
            answer=QMessageBox.question(self.window,'Полный выход','Остановить управляемые процессы и сохранить очередь на паузе? Незавершённый запрос потребует восстановления.')
            if answer!=QMessageBox.Yes:return
        self.closing=True;self.window.banner.setText('Безопасное завершение…')
        self.window.setEnabled(False);self.native.close();self.overlay.hide()
        if not self.bridge.isRunning():self.finished()
        else:self.bridge.request('shutdown')
    def finished(self):
        self.native.close();self.overlay.close();self.tray.hide()
        if self.closing:QApplication.instance().quit()
        else:
            self.window.show_error('Backend остановлен. Очередь не перезапускается автоматически; проверьте состояние и перезапустите приложение.')
            self.window.run_button.setEnabled(False);self.show_main()
