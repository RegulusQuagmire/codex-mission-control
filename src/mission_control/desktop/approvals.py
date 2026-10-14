"""Explicit, version-bound access and execution reviews. Plain text only."""
from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text
from .localized_widgets import QWidget, QDialog, QListWidget, QCheckBox, QMessageBox, QLineEdit, QTabWidget, set_text
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout
from ..safety import fingerprint
from .widgets import label,button,plain,row,STATUS
from .components import StateBanner
from .presentation import mission_details,checkpoint_pending,checkpoint_confirmed,checkpoint_needs_review,turn_control_state,last_attempt,CHECKPOINT_STAGES


WARNING=tr('После подтверждения код может выполняться с правами вашего пользователя Windows. Полноценная изоляция ОС пока отсутствует.')


def access_text(job):
    task=job['task'];spec=job.get('criteria',{})
    lines=[job['title'],tr('Проект: ')+job['project'],tr('Задача:\n')+task['text'],
        tr('Стратегия: ')+enum_label(job['mode']),tr('Максимум попыток: ')+display(job['maxAttempts']),
        tr('Тайм-аут ответа: ')+display(job.get('turnTimeout', 120))+tr(' с'),
        tr('Политика лимитов: ')+enum_label(job.get('policy', {}).get('mode','balanced'))+'\n'+tr('Параметры лимитов (JSON): ')+display(job.get('policy', {})),
        tr('Зависимости: ')+(join_text(', ', job['dependsOn']) or tr('Нет'))]
    if job.get('manual'):lines.append(tr('Ручная конфигурация: ')+job['manual']['model']+' / '+enum_label(job['manual']['effort']))
    if job['type']=='project':
        lines+=[tr('Файлы контекста:\n')+join_text('\n', spec['inputFiles']),
            tr('Разрешено менять:\n')+join_text('\n', spec['writeFiles']),
            tr('Проверки:\n')+join_text('\n\n', (c['name'] + ' (' + message_text({'test':'Тест','build':'Сборка','lint':'Анализ кода','runtime':'Проверка выполнения'}.get(c['kind'],c['kind'])) + ', ' + display(c['timeout']) + tr(' с)\nАргументы: ') + display(c['argv']) for c in spec['commands'])),
            tr('Необходимы изменения: ')+(tr('Да') if spec.get('requireChanges',True) else tr('Нет')),
            tr('Обязательное содержимое файлов: ')+display(spec.get('contains', {}))]
    elif job['type']=='planning':
        lines += [tr('Файлы контекста:\n')+join_text('\n',spec['inputFiles']),
                  tr('Только черновик плана. Запись файлов и исполнение команд не разрешены.')]
    else:lines.append(tr('Точный ожидаемый ответ:\n')+job['expected'])
    lines.append(tr('Оценка задачи: ')+display({k: v for k, v in task.items() if k != 'text'}))
    return join_text('\n\n', lines)


class ResultApprovalDialog(QDialog):
    def __init__(self,value,bridge,parent=None):
        super().__init__(parent);self.value=value;self.bridge=bridge;self.viewed=set()
        self.setWindowTitle(tr('Подтвердить конкретный результат'));self.resize(1000,720)
        layout=QVBoxLayout(self);layout.addWidget(label(tr('Проверка результата · ')+value['missionId'],'section'))
        risk=label(WARNING,'warning');risk.setProperty('fluentSeverity','warning');layout.addWidget(risk)
        layout.addWidget(label(tr('1. Прочитайте каждый раздел до конца · 2. Отметьте просмотр · 3. Подтвердите согласие'),'muted'))
        review=value['review'];self.contents=[(tr('Изменения'),value['diff']),
            (tr('Команды и ограничения'),json.dumps(review['spec'],ensure_ascii=False,indent=2)),
            (tr('Риски'),WARNING+tr('\n\nПроверьте каждый файл рабочей копии, включая файлы проверок. Код может обращаться к сети и файлам пользователя. Подтверждение относится только к этой версии.\n\nReview ID: ')+review['reviewId'])]
        self.contents.extend((name,text) for name,text in sorted(value['sources'].items()))
        split=QHBoxLayout();self.sections=QListWidget();self.sections.setMaximumWidth(260)
        self.sections.addItems([name for name,_ in self.contents]);split.addWidget(self.sections)
        self.viewer=plain();split.addWidget(self.viewer,1);layout.addLayout(split,1)
        self.viewer.setAccessibleName(tr('Содержимое выбранного раздела результата'));self.sections.setAccessibleName(tr('Обязательные разделы просмотра'))
        self.read_button=button(tr('Раздел просмотрен'),self.mark_viewed);layout.addWidget(self.read_button)
        self.progress=label(tr('Просмотрите все разделы и файлы'),'muted');layout.addWidget(self.progress)
        self.consent=QCheckBox(tr('Я понимаю риск и разрешаю выполнение этой версии с правами моего пользователя Windows'))
        self.consent.stateChanged.connect(self.update_ready);layout.addWidget(self.consent)
        self.approve_button=button(tr('Подтвердить выполнение'),self.approve,True)
        layout.addLayout(row(self.approve_button,button(tr('Отклонить результат'),self.reject_result),button(tr('Закрыть'),self.reject)))
        self.sections.currentRowChanged.connect(self.show_section)
        self.viewer.verticalScrollBar().valueChanged.connect(self.update_ready)
        self.viewer.verticalScrollBar().rangeChanged.connect(self.update_ready)
        self.sections.setCurrentRow(0);self.update_ready()
    def show_section(self,index):
        if index>=0:self.viewer.setPlainText(self.contents[index][1]);self.update_ready()
    def mark_viewed(self):
        bar=self.viewer.verticalScrollBar()
        if bar.value()<bar.maximum():return
        self.viewed.add(self.sections.currentRow());self.update_ready()
    def update_ready(self,*_):
        self.read_button.setEnabled(self.viewer.verticalScrollBar().value()>=self.viewer.verticalScrollBar().maximum())
        set_text(self.progress, 'setText', format_text([tr('Просмотрено '), format_value(len(self.viewed), -1, ''), tr(' из '), format_value(len(self.contents), -1, ''), tr(' разделов и файлов')]))
        self.approve_button.setEnabled(len(self.viewed)==len(self.contents) and self.consent.isChecked())
    def approve(self):
        if not self.approve_button.isEnabled():return
        self.bridge.request('approve_result',identity=self.value['missionId'],
            review_id=self.value['review']['reviewId'],accept_user_rights=True)
        self.accept()
    def reject_result(self):
        if QMessageBox.question(self,tr('Отклонить'),tr('Отменить миссию, сохранив её историю и предложенные файлы?'))==QMessageBox.Yes:
            self.bridge.request('control',action='cancel',identity=self.value['missionId']);self.reject()


class AccessDialog(QDialog):
    def __init__(self,job,bridge,parent=None):
        super().__init__(parent);self.job=job;self.bridge=bridge;self.setWindowTitle(tr('Разрешения миссии'));self.resize(820,660)
        layout=QVBoxLayout(self);layout.addWidget(label(job['title'],'section'))
        layout.addWidget(label(tr('Шаг 1 · разрешение на создание результата'),'muted'))
        layout.addWidget(label(tr('Разрешение на создание результата отдельно от разрешения на исполнение. Исходный проект не перезаписывается.')))
        self.viewer=plain(access_text(job))
        layout.addWidget(self.viewer,1)
        self.consent=QCheckBox(tr('Я просмотрел файлы, команды, ограничения и разрешаю эту миссию'))
        layout.addWidget(self.consent);self.approve_button=button(tr('Разрешить миссию'),self.approve,True)
        layout.addLayout(row(self.approve_button,button(tr('Отмена'),self.reject)))
        self.consent.stateChanged.connect(self.update_ready);self.viewer.verticalScrollBar().valueChanged.connect(self.update_ready)
        self.viewer.verticalScrollBar().rangeChanged.connect(self.update_ready);self.update_ready()
    def update_ready(self,*_):
        bar=self.viewer.verticalScrollBar();self.approve_button.setEnabled(self.consent.isChecked() and bar.value()>=bar.maximum())
    def approve(self):
        if self.approve_button.isEnabled():
            self.bridge.request('approve_access',identity=self.job['id'],fingerprint=fingerprint(self.job));self.accept()


class ResultDialog(QDialog):
    def __init__(self,value,bridge,parent=None):
        super().__init__(parent);self.setWindowTitle(tr('Результат и журнал'));self.resize(960,740)
        layout=QVBoxLayout(self);job=value['mission'];layout.addWidget(label(job['title'],'section'))
        run=value.get('run',{});checks=job.get('checks',{})
        attempts=run.get('attempts',job.get('attempts',[]))
        if attempts:checks=attempts[-1].get('validation',checks)
        decision=run.get('decision') or job.get('model') or {}
        summary=join_text('\n\n', [STATUS.get(job['status'], job['status']), tr('Проект: ') + job['project'], tr('Модель: ') + display(decision.get('model', tr('Нет данных'))) + ' / ' + enum_label(decision.get('effort', '—')), tr('Причина выбора: ') + message_text(decision.get('reason', tr('Нет данных'))), tr('Результат проверки: ') + {True: tr('Пройдена'), False: tr('Не пройдена'), None: tr('Нет данных')}[checks.get('passed')], tr('Изменённые файлы:\n') + (join_text('\n', checks.get('changes', [])) or tr('Нет данных')), tr('Сообщение: ') + message_text(checks.get('feedback') or run.get('stopReason') or tr('Нет ошибок'))])
        if job['type']=='text' and attempts:summary+=tr('\n\nОтвет Codex:\n')+attempts[-1].get('outcome',{}).get('text',tr('Нет данных'))
        self.tabs=tabs=QTabWidget();tabs.addTab(plain(summary),tr('Результат'));tabs.addTab(plain(value.get('diff') or tr('Нет сохранённого diff')),tr('Изменения'))
        command_text=join_text('\n\n', (c.get('name', tr('Проверка')) + tr(' · код выхода ') + display(c.get('exitCode', tr('Нет данных'))) + tr(' · тайм-аут ') + display(c.get('timedOut', False)) + '\n' + c.get('output', '') for c in checks.get('commands', [])))
        tabs.addTab(plain(command_text or tr('Проверки ещё не выполнялись')),tr('Проверки'))
        history=[]
        all_attempts=[a for prior in value.get('previousRuns',[]) for a in prior['attempts']]+attempts
        for i,a in enumerate(all_attempts,1):
            d=a['decision'];history.append(format_text([tr('Попытка '), format_value(i, -1, ''), ' · ', format_value(STATUS.get(a['phase'],message_text(a['phase'])), -1, ''), '\n', format_value(d['model'], -1, ''), ' / ', format_value(enum_label(d['effort']), -1, ''), '\n', format_value(message_text(d.get('reason', '')), -1, ''), '\n'])+message_text(a.get('validation', {}).get('feedback', '')))
        tabs.addTab(plain(join_text('\n\n', history) or tr('Нет попыток')),tr('История'))
        self.viewer=plain(json.dumps(value,ensure_ascii=False,indent=2));tabs.addTab(self.viewer,tr('Технические данные'))
        layout.addWidget(tabs,1)
        layout.addWidget(label(tr('Исходный проект не заменяется. Изменения находятся в сохранённой рабочей копии.'),'muted'))
        last=attempts[-1] if attempts else {}
        if last.get('phase')=='paused_turn' or checkpoint_pending(job):
            self._pause_identity=job['id'];self._pause_turn=last.get('turnId')
            self._pause_text=last.get('checkpoint','');self._pause_stale=False;self._pause_sent=False
            stage_ok=run.get('stage') in CHECKPOINT_STAGES
            authorized=checkpoint_confirmed(last) and last.get('continuationApproved')==self._pause_turn
            self._pause_valid=stage_ok and checkpoint_pending(job) and checkpoint_confirmed(last) and (not authorized or bool(job.get('pauseRequested')))
            self.checkpoint_view=plain(self._pause_text or tr('Текст checkpoint не получен. Это не означает отсутствия выполненных действий.'))
            self.checkpoint_view.setAccessibleName(tr('Checkpoint прерванного хода'))
            tabs.addTab(self.checkpoint_view,tr('Checkpoint'));tabs.setCurrentWidget(self.checkpoint_view)
            layout.addWidget(label(tr('Turn ID: ')+(self._pause_turn or tr('Нет данных')),'muted'))
            self.checkpoint_warning=label(tr('Файлы, фоновые процессы и внешние действия могли измениться. Проверьте их самостоятельно. Это согласие разрешает только продолжение данного хода, а не исполнение нового кода.'),'warning')
            self.checkpoint_warning.setProperty('fluentSeverity','warning');layout.addWidget(self.checkpoint_warning)
            self.checkpoint_status=label(tr('Продолжение требует просмотра и подтверждения'),'muted');layout.addWidget(self.checkpoint_status)
            if not self._pause_valid:
                self.checkpoint_status.setText(tr('Продолжение этого хода разрешено') if authorized and stage_ok else tr('Подтверждение завершения хода отсутствует или не совпадает. Продолжение заблокировано.'))
            self.pause_consent=QCheckBox(tr('Я просмотрел checkpoint и сверил состояние файлов, процессов и внешних действий'))
            self.pause_consent.setEnabled(self._pause_valid)
            self.pause_consent.setObjectName('checkpointConsent');layout.addWidget(self.pause_consent)
            self.continue_button=button(tr('Продолжить эту миссию'),self.continue_paused,True)
            self.continue_button.setObjectName('checkpointContinue');self.continue_button.setAutoDefault(False)
            layout.addWidget(self.continue_button)
            self.pause_consent.stateChanged.connect(self.update_pause_ready)
            self.checkpoint_view.verticalScrollBar().valueChanged.connect(self.update_pause_ready)
            self.checkpoint_view.verticalScrollBar().rangeChanged.connect(self.update_pause_ready)
            tabs.currentChanged.connect(self.update_pause_ready)
            if hasattr(bridge,'snapshot'):bridge.snapshot.connect(self.pause_snapshot_changed)
            self.bridge=bridge;self.update_pause_ready()
        uncertain=last.get('validation',{}).get('kind')=='not_retryable'
        if uncertain or job['status']=='needs_attention':
            layout.addWidget(label(tr('Результат операции неизвестен. Изучите журнал и самостоятельно проверьте внешние последствия. Автоматический повтор запрещён.')))
        if uncertain and job['status']=='failed':
            self.consent=QCheckBox(tr('Я сверил фактические последствия и принимаю риск повторения операции'))
            self.typed=QLineEdit();self.typed.setPlaceholderText(tr('Введите ПОВТОРИТЬ после сверки'))
            layout.addWidget(self.consent);layout.addWidget(self.typed)
            self.ack=button(tr('Разрешить отдельную новую попытку'),lambda:self.acknowledge(bridge,job['id']))
            self.consent.stateChanged.connect(self.update_retry_ready);self.typed.textChanged.connect(self.update_retry_ready)
            self.viewer.verticalScrollBar().valueChanged.connect(self.update_retry_ready);self.viewer.verticalScrollBar().rangeChanged.connect(self.update_retry_ready)
            from .i18n import manager
            manager.changed.connect(self.update_retry_ready)
            self.update_retry_ready();layout.addWidget(self.ack)
        layout.addWidget(button(tr('Закрыть'),self.accept))
    def update_pause_ready(self,*_):
        bar=self.checkpoint_view.verticalScrollBar()
        self.continue_button.setEnabled(bool(self._pause_valid and not self._pause_stale and not self._pause_sent
            and self.tabs.currentWidget() is self.checkpoint_view and self.pause_consent.isChecked() and bar.value()>=bar.maximum()))
    def pause_snapshot_changed(self,data):
        job=next((j for j in data.get('missions',[]) if j['id']==self._pause_identity),None)
        attempt=last_attempt(job) if job else {}
        if (not job or not checkpoint_pending(job) or not checkpoint_confirmed(attempt)
                or (job.get('live') or {}).get('stage') not in CHECKPOINT_STAGES
                or attempt.get('turnId')!=self._pause_turn or attempt.get('checkpoint','')!=self._pause_text
                or attempt.get('continuationApproved')==self._pause_turn and not job.get('pauseRequested')):
            self._pause_stale=True;self.pause_consent.setChecked(False);self.pause_consent.setEnabled(False)
            self.checkpoint_status.setText(tr('Состояние изменилось. Закройте окно и откройте checkpoint заново.'))
        self.update_pause_ready()
    def continue_paused(self):
        if not self.continue_button.isEnabled():return
        self._pause_sent=True;self.update_pause_ready()
        self.bridge.request('resume_mission',identity=self._pause_identity,
                            acknowledge_uncertain=True,expected_turn_id=self._pause_turn)
        self.accept()
    def update_retry_ready(self,*_):
        bar=self.viewer.verticalScrollBar()
        self.ack.setEnabled(self.consent.isChecked() and self.typed.text()==tr('ПОВТОРИТЬ') and bar.value()>=bar.maximum())
    def acknowledge(self,bridge,identity):
        if self.ack.isEnabled():bridge.request('control',action='retry',identity=identity,acknowledge_uncertain=True);self.accept()


class ApprovalsPage(QWidget):
    def __init__(self,bridge):
        super().__init__();self.bridge=bridge;self.jobs=[];self.all_jobs=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(16)
        layout.addWidget(label(tr('Контроль подтверждений'),'title'))
        self.attention=label(tr('Нет миссий, требующих разбора'),'section');layout.addWidget(self.attention)
        self.review_state=StateBanner();self.review_state.set_state({'title':tr('Просмотр перед выполнением'),
            'detail':tr('Сначала выберите результат. Подтверждение относится к конкретной версии файлов.'),'severity':'warning'})
        layout.addWidget(self.review_state)
        risk=label(WARNING,'warning');risk.setProperty('fluentSeverity','warning');layout.addWidget(risk)
        self.list=QListWidget();self.list.setAccessibleName(tr('Миссии, требующие подтверждения или разбора'));layout.addWidget(self.list,1)
        self.empty_state=label(tr('Подтверждений пока нет\nКогда результат будет готов, здесь появится миссия для просмотра файлов, команд и рисков.'),'section');self.empty_state.setAlignment(Qt.AlignCenter);layout.addWidget(self.empty_state,1)
        self.review_button=button(tr('Просмотреть результат'),self.review,True);self.inspect_button=button(tr('Результат и журнал'),self.inspect)
        layout.addLayout(row(self.review_button,self.inspect_button))
        self.selection_hint=label(tr('Выберите миссию для просмотра'),'muted');layout.addWidget(self.selection_hint)
        self.selection_detail=label('','muted');layout.addWidget(self.selection_detail)
        self.list.currentRowChanged.connect(self.update_actions)
        layout.addWidget(label(tr('Каждое подтверждение связано с конкретной версией файлов. Изменение файла требует нового просмотра. Массовое подтверждение отсутствует.'),'muted'))
        self.update_actions()
    def update_data(self,data):
        self.all_jobs=data['missions']
        previous_id=(self.selected() or {}).get('id');self.jobs=[j for j in data['missions'] if j['status'] in {'waiting_approval','needs_attention','failed'} or (j.get('live') or {}).get('stage')=='needs_attention' or checkpoint_pending(j)]
        self.list.blockSignals(True)
        self.list.clear();self.list.addItems([j['title']+' · '+(turn_control_state(j)['title'] if checkpoint_pending(j) else
            STATUS.get((j.get('live') or {}).get('stage') or j['status'],j['status'])) for j in self.jobs])
        if self.jobs:self.list.setCurrentRow(next((i for i,j in enumerate(self.jobs) if j['id']==previous_id),0))
        self.list.blockSignals(False);self.list.setVisible(bool(self.jobs));self.empty_state.setVisible(not self.jobs)
        waiting=sum(j['status']=='waiting_approval' and (j.get('live') or {}).get('stage') in {None,'waiting_approval'} or checkpoint_needs_review(j) for j in self.jobs)
        set_text(self.attention, 'setText', format_text([tr('Ожидают подтверждения: '), format_value(waiting, -1, ''), tr(' · требуют разбора: '), format_value(len(self.jobs) - waiting, -1, '')]) if self.jobs else tr('Нет миссий, требующих разбора'))
        self.update_actions()
    def update_actions(self,*_):
        job=self.selected();waiting=bool(job and job['status']=='waiting_approval' and (job.get('live') or {}).get('stage') in {None,'waiting_approval'});checkpoint=checkpoint_pending(job)
        self.review_button.setEnabled(waiting or checkpoint);self.inspect_button.setEnabled(bool(job))
        self.review_button.setText(tr('Просмотреть checkpoint') if checkpoint else tr('Просмотреть результат'))
        if checkpoint:self.review_state.set_state(turn_control_state(job))
        else:self.review_state.set_state(dict(title=tr('Просмотр перед выполнением'),detail=tr('Сначала выберите результат. Подтверждение относится к конкретной версии файлов.'),severity='warning'))
        set_text(self.selection_detail,'setText',mission_details(job,self.all_jobs))
        set_text(self.selection_hint, 'setText', tr('Продолжение хода, доступ к проекту и исполнение результата требуют отдельных подтверждений.') if checkpoint else tr('Просмотрите файлы и команды перед разрешением выполнения этой версии.') if waiting else tr('Изучите результат и журнал, чтобы определить дальнейшее действие.') if job else tr('Выберите миссию для просмотра'))
    def selected(self):
        i=self.list.currentRow();return self.jobs[i] if 0<=i<len(self.jobs) else None
    def review(self):
        job=self.selected()
        if checkpoint_pending(job):self.bridge.request('result',identity=job['id'])
        elif job and job['status']=='waiting_approval' and (job.get('live') or {}).get('stage') in {None,'waiting_approval'}:self.bridge.request('review_result',identity=job['id'])
    def inspect(self):
        job=self.selected()
        if job:self.bridge.request('result',identity=job['id'])
