"""Explicit, version-bound access and execution reviews. Plain text only."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QListWidget,
    QCheckBox,QMessageBox,QLineEdit,QTabWidget)
from ..safety import fingerprint
from .widgets import label,button,plain,row,STATUS


WARNING='После подтверждения код может выполняться с правами вашего пользователя Windows. Полноценная изоляция ОС пока отсутствует.'


def access_text(job):
    task=job['task'];spec=job.get('criteria',{})
    lines=[job['title'],'Проект: '+job['project'],'Задача:\n'+task['text'],
        'Стратегия: '+job['mode'],'Максимум попыток: '+str(job['maxAttempts']),
        'Тайм-аут ответа: '+str(job.get('turnTimeout',120))+' с',
        'Политика лимитов: '+str(job.get('policy',{})),
        'Зависимости: '+(', '.join(job['dependsOn']) or 'Нет')]
    if job.get('manual'):lines.append('Ручная конфигурация: '+job['manual']['model']+' / '+job['manual']['effort'])
    if job['type']=='project':
        lines+=['Файлы контекста:\n'+'\n'.join(spec['inputFiles']),
            'Разрешено менять:\n'+'\n'.join(spec['writeFiles']),
            'Проверки:\n'+'\n\n'.join(c['name']+' ('+c['kind']+', '+str(c['timeout'])+' с)\nАргументы: '+str(c['argv']) for c in spec['commands']),
            'Необходимы изменения: '+str(spec.get('requireChanges',True)),
            'Обязательное содержимое файлов: '+str(spec.get('contains',{}))]
    else:lines.append('Точный ожидаемый ответ:\n'+job['expected'])
    lines.append('Оценка задачи: '+str({k:v for k,v in task.items() if k!='text'}))
    return '\n\n'.join(lines)


class ResultApprovalDialog(QDialog):
    def __init__(self,value,bridge,parent=None):
        super().__init__(parent);self.value=value;self.bridge=bridge;self.viewed=set()
        self.setWindowTitle('Подтвердить конкретный результат');self.resize(1000,720)
        layout=QVBoxLayout(self);layout.addWidget(label('Проверка результата · '+value['missionId'],'section'))
        risk=label(WARNING,'warning');risk.setProperty('fluentSeverity','warning');layout.addWidget(risk)
        layout.addWidget(label('1. Прочитайте каждый раздел до конца · 2. Отметьте просмотр · 3. Подтвердите согласие','muted'))
        review=value['review'];self.contents=[('Изменения',value['diff']),
            ('Команды и ограничения',json.dumps(review['spec'],ensure_ascii=False,indent=2)),
            ('Риски',WARNING+'\n\nПроверьте каждый файл рабочей копии, включая файлы проверок. Код может обращаться к сети и файлам пользователя. Подтверждение относится только к этой версии.\n\nReview ID: '+review['reviewId'])]
        self.contents.extend((name,text) for name,text in sorted(value['sources'].items()))
        split=QHBoxLayout();self.sections=QListWidget();self.sections.setMaximumWidth(260)
        self.sections.addItems([name for name,_ in self.contents]);split.addWidget(self.sections)
        self.viewer=plain();split.addWidget(self.viewer,1);layout.addLayout(split,1)
        self.viewer.setAccessibleName('Содержимое выбранного раздела результата');self.sections.setAccessibleName('Обязательные разделы просмотра')
        self.read_button=button('Раздел просмотрен',self.mark_viewed);layout.addWidget(self.read_button)
        self.progress=label('Просмотрите все разделы и файлы','muted');layout.addWidget(self.progress)
        self.consent=QCheckBox('Я понимаю риск и разрешаю выполнение этой версии с правами моего пользователя Windows')
        self.consent.stateChanged.connect(self.update_ready);layout.addWidget(self.consent)
        self.approve_button=button('Подтвердить выполнение',self.approve,True)
        layout.addLayout(row(self.approve_button,button('Отклонить результат',self.reject_result),button('Закрыть',self.reject)))
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
        self.progress.setText(f'Просмотрено {len(self.viewed)} из {len(self.contents)} разделов и файлов')
        self.approve_button.setEnabled(len(self.viewed)==len(self.contents) and self.consent.isChecked())
    def approve(self):
        if not self.approve_button.isEnabled():return
        self.bridge.request('approve_result',identity=self.value['missionId'],
            review_id=self.value['review']['reviewId'],accept_user_rights=True)
        self.accept()
    def reject_result(self):
        if QMessageBox.question(self,'Отклонить','Отменить миссию, сохранив её историю и предложенные файлы?')==QMessageBox.Yes:
            self.bridge.request('control',action='cancel',identity=self.value['missionId']);self.reject()


class AccessDialog(QDialog):
    def __init__(self,job,bridge,parent=None):
        super().__init__(parent);self.job=job;self.bridge=bridge;self.setWindowTitle('Разрешения миссии');self.resize(820,660)
        layout=QVBoxLayout(self);layout.addWidget(label(job['title'],'section'))
        layout.addWidget(label('Шаг 1 · разрешение на создание результата','muted'))
        layout.addWidget(label('Разрешение на создание результата отдельно от разрешения на исполнение. Исходный проект не перезаписывается.'))
        self.viewer=plain(access_text(job))
        layout.addWidget(self.viewer,1)
        self.consent=QCheckBox('Я просмотрел файлы, команды, ограничения и разрешаю эту миссию')
        layout.addWidget(self.consent);self.approve_button=button('Разрешить миссию',self.approve,True)
        layout.addLayout(row(self.approve_button,button('Отмена',self.reject)))
        self.consent.stateChanged.connect(self.update_ready);self.viewer.verticalScrollBar().valueChanged.connect(self.update_ready)
        self.viewer.verticalScrollBar().rangeChanged.connect(self.update_ready);self.update_ready()
    def update_ready(self,*_):
        bar=self.viewer.verticalScrollBar();self.approve_button.setEnabled(self.consent.isChecked() and bar.value()>=bar.maximum())
    def approve(self):
        if self.approve_button.isEnabled():
            self.bridge.request('approve_access',identity=self.job['id'],fingerprint=fingerprint(self.job));self.accept()


class ResultDialog(QDialog):
    def __init__(self,value,bridge,parent=None):
        super().__init__(parent);self.setWindowTitle('Результат и журнал');self.resize(960,740)
        layout=QVBoxLayout(self);job=value['mission'];layout.addWidget(label(job['title'],'section'))
        run=value.get('run',{});checks=job.get('checks',{})
        attempts=run.get('attempts',job.get('attempts',[]))
        if attempts:checks=attempts[-1].get('validation',checks)
        decision=run.get('decision') or job.get('model') or {}
        summary='\n\n'.join([STATUS.get(job['status'],job['status']),'Проект: '+job['project'],
            'Модель: '+str(decision.get('model','Нет данных'))+' / '+str(decision.get('effort','—')),
            'Причина выбора: '+str(decision.get('reason','Нет данных')),
            'Результат проверки: '+{True:'Пройдена',False:'Не пройдена',None:'Нет данных'}[checks.get('passed')],
            'Изменённые файлы:\n'+('\n'.join(checks.get('changes',[])) or 'Нет данных'),
            'Сообщение: '+str(checks.get('feedback') or run.get('stopReason') or 'Нет ошибок')])
        if job['type']=='text' and attempts:summary+='\n\nОтвет Codex:\n'+attempts[-1].get('outcome',{}).get('text','Нет данных')
        tabs=QTabWidget();tabs.addTab(plain(summary),'Результат');tabs.addTab(plain(value.get('diff') or 'Нет сохранённого diff'),'Изменения')
        command_text='\n\n'.join(c.get('name','Проверка')+' · код выхода '+str(c.get('exitCode','Нет данных'))+
            ' · тайм-аут '+str(c.get('timedOut',False))+'\n'+c.get('output','') for c in checks.get('commands',[]))
        tabs.addTab(plain(command_text or 'Проверки ещё не выполнялись'),'Проверки')
        history=[]
        all_attempts=[a for prior in value.get('previousRuns',[]) for a in prior['attempts']]+attempts
        for i,a in enumerate(all_attempts,1):
            d=a['decision'];history.append(f'Попытка {i} · {a["phase"]}\n{d["model"]} / {d["effort"]}\n{d.get("reason","")}\n'+str(a.get('validation',{}).get('feedback','')))
        tabs.addTab(plain('\n\n'.join(history) or 'Нет попыток'),'История')
        self.viewer=plain(json.dumps(value,ensure_ascii=False,indent=2));tabs.addTab(self.viewer,'Технические данные')
        layout.addWidget(tabs,1)
        layout.addWidget(label('Исходный проект не заменяется. Изменения находятся в сохранённой рабочей копии.','muted'))
        last=attempts[-1] if attempts else {}
        uncertain=last.get('validation',{}).get('kind')=='not_retryable'
        if uncertain or job['status']=='needs_attention':
            layout.addWidget(label('Результат операции неизвестен. Изучите журнал и самостоятельно проверьте внешние последствия. Автоматический повтор запрещён.'))
        if uncertain and job['status']=='failed':
            self.consent=QCheckBox('Я сверил фактические последствия и принимаю риск повторения операции')
            self.typed=QLineEdit();self.typed.setPlaceholderText('Введите ПОВТОРИТЬ после сверки')
            layout.addWidget(self.consent);layout.addWidget(self.typed)
            self.ack=button('Разрешить отдельную новую попытку',lambda:self.acknowledge(bridge,job['id']))
            def ready(*_):
                bar=self.viewer.verticalScrollBar();self.ack.setEnabled(self.consent.isChecked() and self.typed.text()=='ПОВТОРИТЬ' and bar.value()>=bar.maximum())
            self.consent.stateChanged.connect(ready);self.typed.textChanged.connect(ready)
            self.viewer.verticalScrollBar().valueChanged.connect(ready);self.viewer.verticalScrollBar().rangeChanged.connect(ready)
            ready();layout.addWidget(self.ack)
        layout.addWidget(button('Закрыть',self.accept))
    def acknowledge(self,bridge,identity):
        if self.ack.isEnabled():bridge.request('control',action='retry',identity=identity,acknowledge_uncertain=True);self.accept()


class ApprovalsPage(QWidget):
    def __init__(self,bridge):
        super().__init__();self.bridge=bridge;self.jobs=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(16)
        layout.addWidget(label('Контроль подтверждений','title'))
        self.attention=label('Нет миссий, требующих разбора','section');layout.addWidget(self.attention)
        risk=label(WARNING,'warning');risk.setProperty('fluentSeverity','warning');layout.addWidget(risk)
        self.list=QListWidget();self.list.setAccessibleName('Миссии, требующие подтверждения или разбора');layout.addWidget(self.list,1)
        self.empty_state=label('Подтверждений пока нет\nКогда результат будет готов, здесь появится миссия для просмотра файлов, команд и рисков.','section');self.empty_state.setAlignment(Qt.AlignCenter);layout.addWidget(self.empty_state,1)
        self.review_button=button('Просмотреть результат',self.review,True);self.inspect_button=button('Результат и журнал',self.inspect)
        layout.addLayout(row(self.review_button,self.inspect_button))
        self.selection_hint=label('Выберите миссию для просмотра','muted');layout.addWidget(self.selection_hint)
        self.list.currentRowChanged.connect(self.update_actions)
        layout.addWidget(label('Каждое подтверждение связано с конкретной версией файлов. Изменение файла требует нового просмотра. Массовое подтверждение отсутствует.','muted'))
        self.update_actions()
    def update_data(self,data):
        previous_id=(self.selected() or {}).get('id');self.jobs=[j for j in data['missions'] if j['status'] in {'waiting_approval','needs_attention','failed'}]
        self.list.blockSignals(True)
        self.list.clear();self.list.addItems([j['title']+' · '+STATUS.get(j['status'],j['status']) for j in self.jobs])
        if self.jobs:self.list.setCurrentRow(next((i for i,j in enumerate(self.jobs) if j['id']==previous_id),0))
        self.list.blockSignals(False);self.list.setVisible(bool(self.jobs));self.empty_state.setVisible(not self.jobs)
        waiting=sum(j['status']=='waiting_approval' for j in self.jobs)
        self.attention.setText(f'Ожидают подтверждения: {waiting} · требуют разбора: {len(self.jobs)-waiting}' if self.jobs else 'Нет миссий, требующих разбора')
        self.update_actions()
    def update_actions(self,*_):
        job=self.selected();waiting=bool(job and job['status']=='waiting_approval')
        self.review_button.setEnabled(waiting);self.inspect_button.setEnabled(bool(job))
        self.selection_hint.setText('Просмотрите файлы и команды перед разрешением выполнения этой версии.' if waiting else 'Изучите результат и журнал, чтобы определить дальнейшее действие.' if job else 'Выберите миссию для просмотра')
    def selected(self):
        i=self.list.currentRow();return self.jobs[i] if 0<=i<len(self.jobs) else None
    def review(self):
        job=self.selected()
        if job and job['status']=='waiting_approval':self.bridge.request('review_result',identity=job['id'])
    def inspect(self):
        job=self.selected()
        if job:self.bridge.request('result',identity=job['id'])
