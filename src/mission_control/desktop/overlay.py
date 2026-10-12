from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text
from .localized_widgets import QWidget, set_text
from PySide6.QtCore import Qt,QPoint,Signal,QAbstractAnimation
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout
from .widgets import label,button,limits_text,STATUS
from .visuals import MissionBackdrop,RouterNetwork,animation
from .presentation import quota_freshness,control_state
from .components import severity


class MissionOverlay(MissionBackdrop):
    hide_requested=Signal()
    preferences_changed=Signal(dict)
    def __init__(self,bridge,open_main):
        super().__init__();self.setWindowFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating);self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName('surface');self.setWindowTitle('Mission Control Overlay')
        self.bridge=bridge;self.open_main=open_main;self.compact=False;self._drag=None;self.reduced_motion=False;self.disclosure=None;self._restored=False
        layout=QVBoxLayout(self);layout.setContentsMargins(14,10,14,14)
        self.header=label('MISSION CONTROL','section');self.header.setToolTip(tr('Перетащите панель за заголовок'))
        self.header.mousePressEvent=self.drag_start;self.header.mouseMoveEvent=self.drag_move;self.header.mouseReleaseEvent=self.drag_end
        layout.addLayout(self.header_row())
        self.summary=label(tr('Нет активной миссии'));layout.addWidget(self.summary)
        self.control_status=label('','section');layout.addWidget(self.control_status)
        self.network=RouterNetwork(compact=True);layout.addWidget(self.network)
        self.disclosure=animation(self.network,b'maximumHeight',130,130,240)
        self.disclosure.valueChanged.connect(lambda _:self.adjustSize())
        self.details=label('','muted');layout.addWidget(self.details)
        self.approval=label('','warning');layout.addWidget(self.approval)
        layout.addLayout(self.actions());self.setFixedWidth(430);self.adjustSize()
    def header_row(self):
        layout=QHBoxLayout();layout.addWidget(self.header,1)
        compact=button('−',self.toggle_compact);compact.setToolTip(tr('Компактный / расширенный режим'))
        hide=button('×',self.request_hide);hide.setToolTip(tr('Скрыть оверлей'))
        layout.addWidget(compact);layout.addWidget(hide);return layout
    def actions(self):
        layout=QHBoxLayout();layout.addWidget(button(tr('Открыть миссию'),self.open_main))
        layout.addWidget(button(tr('Пауза'),lambda:self.bridge.request('control',action='pause')));return layout
    def drag_start(self,event):
        if event.button()==Qt.LeftButton:self._drag=event.globalPosition().toPoint()-self.frameGeometry().topLeft();event.accept()
    def drag_move(self,event):
        if self._drag is not None:self.move(event.globalPosition().toPoint()-self._drag);event.accept()
    def drag_end(self,event):
        self._drag=None;self.preferences_changed.emit({'overlayX':self.x(),'overlayY':self.y()})
    def set_reduced_motion(self,value):
        self.reduced_motion=bool(value);self.network.set_reduced_motion(value)
        if value and self.disclosure:
            self.disclosure.stop();self.network.setMaximumHeight(0 if self.compact else 130)
            self.adjustSize()
    def toggle_compact(self):
        self.compact=not self.compact;self.details.setVisible(not self.compact)
        if self.disclosure:self.disclosure.stop()
        target=0 if self.compact else 130
        # Text collapses immediately; the network makes a short finite transition.
        self.network.setMinimumHeight(0)
        if self.reduced_motion:self.network.setMaximumHeight(target)
        else:
            self.disclosure.setStartValue(self.network.height());self.disclosure.setEndValue(target);self.disclosure.start()
        self.layout().activate();self.adjustSize()
        self.preferences_changed.emit({'overlayCompact':self.compact})
    def request_hide(self):self.hide_requested.emit();self.hide()
    def set_pinned(self,value):
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint)==value:return
        visible=self.isVisible();self.setWindowFlag(Qt.WindowStaysOnTopHint,value)
        if visible:self.show()
    def update_data(self,data):
        state=control_state(data);set_text(self.control_status,'setText',state['title']);severity(self.control_status,state['severity'])
        self.set_reduced_motion(data['preferences'].get('reducedMotion',False));self.network.set_snapshot(data)
        if not self._restored:
            self.compact=bool(data['preferences'].get('overlayCompact',False));self._restored=True
        if self.compact and not (self.disclosure and self.disclosure.state()==QAbstractAnimation.Running):
            self.network.setMinimumHeight(0);self.network.setMaximumHeight(0);self.details.hide()
        jobs=data['missions'];active=next((j for j in jobs if j['id']==data['active']),None)
        next_job=next((j for j in sorted(jobs,key=lambda j:(-j['priority'],j['sequence'])) if j['status']=='pending'),None)
        state=tr('Пауза') if data['paused'] else tr('Готово')
        if active:
            live=active.get('live',{});decision=live.get('decision') or active.get('model') or {}
            state=STATUS.get(live.get('stage') or active['status'],live.get('stage') or active['status'])
            set_text(self.summary, 'setText', state + '\n' + active['title'] + '\n' + decision.get('model', tr('Модель не выбрана')) + ' / ' + enum_label(decision.get('effort','—')))
        else:set_text(self.summary, 'setText', state + tr(' · Нет активной миссии'))
        freshness,_=quota_freshness(data)
        set_text(self.details, 'setText', limits_text(data['limits'])+'\n\n'+freshness + tr('\n\nДалее: ') + (next_job['title'] if next_job else tr('Очередь пуста')) + tr('\nТолько миссии Mission Control'))
        needs=sum(j['status']=='waiting_approval' for j in jobs)
        set_text(self.approval, 'setText', format_text([tr('Требуется просмотр: '), format_value(needs, -1, ''), tr('. Код не исполняется без согласия.')]) if needs else '')
        self.approval.setVisible(bool(needs))
        self.set_pinned(data['preferences'].get('overlayPinned',True))
        self.adjustSize()

    def closeEvent(self,event):
        self.network.pulse.stop()
        if self.disclosure:self.disclosure.stop()
        super().closeEvent(event)
