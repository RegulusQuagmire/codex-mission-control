from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text
from .localized_widgets import QWidget, QComboBox, set_text
from PySide6.QtWidgets import QVBoxLayout
from .widgets import label,button,row,plain,panel
from .components import ResponsiveColumns,StateBanner
from .presentation import model_facts,active_mission,quota_freshness
from .visuals import RouterNetwork
from .i18n import manager
from PySide6.QtCore import QTimer
from ..route_inspection import inspection_fingerprint
import time


class RouterPage(QWidget):
    def __init__(self,bridge):
        super().__init__();self.bridge=bridge;self.models=[];self.data={};self.facts=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16)
        layout.addWidget(label(tr('Маршрутизация моделей'),'title'))
        layout.addWidget(label(tr('Каждая новая задача получает собственную оценку сложности. Результаты проверок могут повысить модель в автоматическом режиме.'),'muted'))
        self.route_state=StateBanner();layout.addWidget(self.route_state)
        self.preview_result=None;self.preview_pending=False;self.preview_signature=None
        preview,preview_layout=panel(tr('Оценка выбранной миссии'))
        self.inspection_mission=QComboBox();self.inspection_mission.setAccessibleName(tr('Миссия для оценки Router'))
        self.inspection_mission.currentIndexChanged.connect(self.select_preview)
        self.preview_button=button(tr('Оценить без отправки'),self.request_preview,True)
        preview_layout.addLayout(row(self.inspection_mission,self.preview_button))
        self.recommendation=plain();self.recommendation.setMinimumHeight(190)
        self.recommendation.setAccessibleName(tr('Объяснение выбора Router'));preview_layout.addWidget(self.recommendation)
        preview_layout.addWidget(label(tr('Оценка не отправляет inference и не разрешает запуск. Перед каждой отправкой backend заново проверяет ограничения и approvals.'),'muted'))
        layout.addWidget(preview)
        bridge.result.connect(self.receive_preview);bridge.error.connect(self.preview_error)
        manager.changed.connect(self.render_preview)
        self.preview_timer=QTimer(self);self.preview_timer.setInterval(1000)
        self.preview_timer.timeout.connect(self.expire_preview);self.preview_timer.start()
        self.render_preview()
        graph,graph_layout=panel(tr('Наблюдаемый маршрут'));self.network=RouterNetwork();graph_layout.addWidget(self.network)
        graph_layout.addWidget(label(tr('Выбор узла показывает подробности и не меняет маршрут миссии.'),'muted'))
        inspector,inspector_layout=panel(tr('Инспекция модели'));self.inspection=plain();self.inspection.setMinimumHeight(220)
        self.inspection.setAccessibleName(tr('Инспекция модели'));inspector_layout.addWidget(self.inspection)
        layout.addWidget(ResponsiveColumns(graph,inspector))
        self.network.model_inspected.connect(self.inspect_model)
        strategy,strategy_layout=panel(tr('Управление моделями'))
        self.mode=QComboBox();self.mode.setAccessibleName(tr('Стратегия новых миссий'))
        for title,value in [(tr('Economy — беречь лимиты'),'economy'),(tr('Balanced — баланс'),'balanced'),(tr('Quality — качество'),'quality')]:self.mode.addItem(title,value)
        strategy_layout.addLayout(row(self.mode,button(tr('Применить к новым задачам'),lambda:bridge.request('save_preferences',values={'mode':self.mode.currentData()}),True)))
        strategy_layout.addWidget(label(tr('Ручной режим выбирается в редакторе задачи. Он сохраняет конкретную модель и effort, без автоматической эскалации.'),'muted'))
        layout.addWidget(strategy)
        catalog,catalog_layout=panel(tr('02 · Доступный каталог Codex'))
        self.catalog_state=label(tr('Нет данных · подключите Codex для загрузки каталога'),'muted');catalog_layout.addWidget(self.catalog_state)
        self.catalog=QComboBox();self.effort=QComboBox();self.catalog.currentIndexChanged.connect(self.update_efforts)
        self.catalog.currentIndexChanged.connect(self.update_inspection)
        self.catalog.setAccessibleName(tr('Модель из каталога Codex'));self.effort.setAccessibleName(tr('Поддерживаемый reasoning effort'))
        catalog_layout.addLayout(row(self.catalog,self.effort,button(tr('Обновить каталог'),lambda:bridge.request('refresh_connection'))))
        self.model_detail=label(tr('Выберите модель, чтобы увидеть поддерживаемые уровни reasoning effort.'),'muted');catalog_layout.addWidget(self.model_detail)
        layout.addWidget(catalog)
        layout.addWidget(label(tr('Ограничения лимитов действуют отдельно для всех моделей; доступность новой отправки проверяет backend.'),'muted'))
        layout.addWidget(label(tr('История решений'),'section'));self.history=plain();self.history.setMinimumHeight(160);self.history.setAccessibleName(tr('История решений маршрутизатора'));layout.addWidget(self.history,1)
    def inspect_model(self,identity):
        index=self.catalog.findData(identity)
        if index>=0:self.catalog.setCurrentIndex(index)
        self.update_inspection(identity)
    def update_inspection(self,identity=None):
        identity=identity if isinstance(identity,str) else self.catalog.currentData()
        fact=next((f for f in self.facts if f['model']==identity),None)
        if not fact:
            self.inspection.setPlainText(tr('Нет данных о модели. Обновите подключение для загрузки каталога.'));return
        self.network.inspected=identity;self.network.update()
        state=tr('Доступна по каталогу и политике') if fact['available'] else tr('Недоступна для новой отправки')
        text=fact['title']+'\nID: '+fact['model']+'\n\n'+state
        if fact['chosen']:text+='\n'+tr('Выбрана контроллером')
        text+='\n\n'+tr('Разрешённое рассуждение: ')+(join_text(', ',(enum_label(e) for e in fact['efforts'])) or tr('Не подтверждено'))
        text+='\n\n'+fact['notes']
        self.inspection.setPlainText(text)
    def update_efforts(self):
        self.effort.clear();model=next((m for m in self.models if m['model']==self.catalog.currentData()),None)
        if model:self.effort.addEnums([x['reasoningEffort'] for x in model.get('supportedReasoningEfforts',[])])
        self.effort.setEnabled(bool(model and self.effort.count()))
        if hasattr(self,'model_detail'):
            set_text(self.model_detail, 'setText', model.get('description') or 'ID: ' + model['model'] if model else tr('Нет данных о модели. Обновите подключение для загрузки каталога.'))
    def update_data(self,data):
        self.data=data;self.facts=model_facts(data);self.network.set_snapshot(data)
        self.network.availability={f['model']:f['available'] for f in self.facts}
        self.network.set_reduced_motion(data['preferences'].get('reducedMotion',False))
        active=active_mission(data) or {};decision=active.get('live',{}).get('decision') or active.get('model') or {}
        fresh,_=quota_freshness(data)
        mode='manual' if active.get('manual') else active.get('mode',data['preferences'].get('mode','balanced'))
        self.route_state.set_state({'title':tr('Режим активной миссии: ')+enum_label(mode),
            'detail':message_text(decision.get('reason') or tr('Причина выбора не сохранена'))+'\n'+fresh,'severity':'info'})
        self.mode.setCurrentIndex(max(0,self.mode.findData(data['preferences'].get('mode','balanced'))))
        entries=[(f['title'],f['model']) for f in self.facts]
        if self.models!=data['models'] or entries!=getattr(self,'catalog_entries',None):
            previous=self.catalog.currentData();self.models=data['models'];self.catalog_entries=entries
            self.catalog.blockSignals(True);self.catalog.clear()
            for title,identity in entries:self.catalog.addItem(title,identity)
            index=self.catalog.findData(previous)
            if index>=0:self.catalog.setCurrentIndex(index)
            self.catalog.blockSignals(False)
            self.update_efforts()
        self.catalog.setEnabled(bool(entries))
        self.effort.setEnabled(bool(self.effort.count()))
        if not self.models:set_text(self.model_detail, 'setText', tr('Нет данных о модели. Обновите подключение для загрузки каталога.'))
        self.update_inspection()
        set_text(self.catalog_state, 'setText', format_text([tr('Моделей в текущем каталоге: '), format_value(len(self.models), -1, ''), tr(' · уровни effort получены из Codex')]) if self.models else tr('Нет данных · каталог Codex ещё не получен'))
        lines=[]
        for job in data['missions']:
            attempts=job.get('pastAttempts',[])+(job.get('live',{}).get('attempts') or job.get('attempts',[]))
            for i,a in enumerate(attempts,1):
                d=a['decision'];outcome=a.get('validation',{}).get('passed')
                lines.append(format_text([format_value(job['title'], -1, ''), tr(' · попытка '), format_value(i, -1, ''), '\n', format_value(d['model'], -1, ''), ' / ', format_value(enum_label(d['effort']), -1, ''), ' · ', format_value(enum_label(d.get('complexity','—').lower()), -1, ''), '\n', format_value(message_text(d.get('reason', '')), -1, ''), tr('\nПроверка: ')])+{True:tr('пройдена'),False:tr('не пройдена'),None:tr('нет результата')}[outcome])
        text=join_text('\n\n', lines) or tr('Решений пока нет. Каталог загружается из Codex.')
        if self.history.toPlainText()!=text:self.history.setPlainText(text)
        previous=self.inspection_mission.currentData()
        self.inspection_mission.blockSignals(True);self.inspection_mission.clear()
        for job in data['missions']:self.inspection_mission.addItem(job['title'],job['id'])
        index=self.inspection_mission.findData(previous)
        if index>=0:self.inspection_mission.setCurrentIndex(index)
        self.inspection_mission.blockSignals(False);self.select_preview()

    def select_preview(self,*_):
        identity=self.inspection_mission.currentData()
        signature=inspection_fingerprint(self.data,identity) if identity else None
        if signature!=self.preview_signature:
            self.preview_result=None;self.preview_pending=False;self.preview_signature=signature
        self.preview_button.setEnabled(bool(identity) and not self.preview_pending)
        self.render_preview()

    def request_preview(self):
        identity=self.inspection_mission.currentData()
        if not identity or self.preview_pending:return
        self.preview_pending=True;self.preview_button.setEnabled(False)
        self.bridge.request('inspect_route',identity=identity)

    def receive_preview(self,operation,value):
        if operation!='inspect_route' or not isinstance(value,dict):return
        if value.get('identity')!=self.inspection_mission.currentData() or value.get('fingerprint')!=self.preview_signature:return
        self.preview_result=value;self.preview_pending=False
        self.preview_button.setEnabled(bool(self.inspection_mission.currentData()))
        self.render_preview();self.expire_preview()

    def preview_error(self,*_):
        self.preview_pending=False;self.preview_button.setEnabled(bool(self.inspection_mission.currentData()))

    def expire_preview(self):
        if self.preview_result and self.preview_result.get('expiresAt') is not None and self.preview_result['expiresAt']<=time.time():
            self.preview_result=None;self.render_preview()

    def render_preview(self,*_):
        value=self.preview_result
        if not value:
            self.recommendation.setPlainText(tr('Выберите миссию и выполните оценку. Изменение данных требует новой проверки.'));return
        assessment=value['assessment'];decision=value.get('decision')
        lines=[tr('Сложность: {level} · индекс признаков {score}/{maximum}',level=enum_label(assessment['complexity'].lower()),score=assessment['score'],maximum=assessment['maximum']),
            tr('Индекс — локальная эвристика, а не вероятность успеха или истинная сложность.')]
        if decision:
            lines += [tr('Сохранённая конфигурация · текущий turn не меняется') if value['retained'] else tr('Рекомендуемая конфигурация'),
                decision['model']+' / '+str(tr('Reasoning effort'))+': '+str(enum_label(decision['effort']))]
            lines.append(tr('Режим выбранной миссии: {mode}',mode=enum_label('manual' if value['manual'] else decision.get('mode','balanced'))))
            if decision.get('profileSource','').startswith('unranked'):
                lines.append(tr('Сравнительные возможности неизвестны; использован default каталога или стабильный exact ID.'))
            if value['manual']:lines.append(tr('Ручной выбор сохранён; автоматическая эскалация отключена.'))
            constraints=value.get('currentConstraints',{})
            if constraints.get('effortCeiling'):lines.append(tr('Текущий предел effort: {effort}',effort=enum_label(constraints['effortCeiling'])))
            lines.append(tr('Разрешено каталогом и политикой: {efforts}',efforts=join_text(', ',[enum_label(e) for e in constraints.get('allowedEfforts',[])])))
            evidence=decision.get('history') or {}
            if evidence:
                lines.append(tr('История решения: {success} успешно / {failure} с ошибкой; минимум {minimum} наблюдений.',success=evidence.get('success',0),failure=evidence.get('failure',0),minimum=evidence.get('minimumSamples',8)))
                lines.append(tr('История изменила предпочтительный профиль после повторных проверенных ошибок.') if evidence.get('adjusted') else tr('История не обосновывает изменение предпочтительного профиля.'))
                if evidence.get('status')=='insufficient':lines.append(tr('Нет достаточной истории для этого решения.'))
                for item in evidence.get('compared',[]):
                    if evidence.get('adjusted') and item.get('unreliable'):
                        lines.append(tr('История отклонённого профиля {model} / {effort}: {success} успешно / {failure} с ошибкой.',model=item['model'],effort=enum_label(item['effort']),success=item['success'],failure=item['failure']))
            else:lines.append(tr('Нет достаточной истории для этого решения.'))
            alternatives=decision.get('alternatives',[])[:3]
            if alternatives:lines.append(tr('Другие варианты по текущим проверкам: ')+join_text(', ',[a['model']+' / '+str(enum_label(a['effort'])) for a in alternatives]))
        else:lines.append(tr('Нет допустимой конфигурации. Проверьте каталог и Model Policy.'))
        lines.append(tr('Признаки оценки:'))
        lines.extend(message_text(signal) for signal in assessment['signals'])
        lines.append(tr('Осталось попыток: {count}',count=value['remainingAttempts']))
        blocks={'model_policy':'Модель или effort запрещены текущим каталогом/политикой.',
            'credit_gate':'Credit Policy блокирует отправку: ', 'limit_gate':'Лимиты блокируют отправку: ',
            'attempt_budget':'Бюджет попыток исчерпан.', 'checkpoint_review':'Требуется отдельное подтверждение checkpoint.',
            'outcome_or_active':'Ход активен или исход неизвестен; новая отправка запрещена.',
            'terminal_mission':'Миссия завершена; оценка не создаёт новую задачу.',
            'execution_approval':'Требуется независимое разрешение исполнения результата.',
            'queue_paused':'Очередь на паузе.'}
        for block in value['blocked']:
            line=tr(blocks[block])
            if block in {'credit_gate','limit_gate'}:
                gate=value['creditGate' if block=='credit_gate' else 'limitGate']
                line+=message_text(gate['reason'])
            lines.append(line)
        self.recommendation.setPlainText(join_text('\n',lines))
