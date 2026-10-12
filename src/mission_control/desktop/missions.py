"""Mission editing and inspection; no project code runs in this module."""
import json
from pathlib import Path
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QFormLayout,QLineEdit,QPlainTextEdit,
    QComboBox,QSpinBox,QListWidget,QListWidgetItem,QFileDialog,QDialogButtonBox,QTableWidget,
    QTableWidgetItem,QHeaderView,QAbstractItemView,QMessageBox,QInputDialog,QScrollArea)
from .widgets import label,button,row,plain,STATUS,duration


class CommandDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Команда проверки');self.resize(560,400)
        form=QFormLayout(self);self.name=QLineEdit('Проверка');self.kind=QComboBox()
        self.kind.addItems(['test','build','lint','runtime']);self.executable=QLineEdit()
        self.args=QPlainTextEdit();self.args.setPlaceholderText('Один аргумент на строку. Без внешних кавычек.\nНапример: -m\npytest\n-q')
        self.timeout=QSpinBox();self.timeout.setRange(1,3600);self.timeout.setValue(120)
        form.addRow('Название',self.name);form.addRow('Тип',self.kind)
        form.addRow('Программа',row(self.executable,button('Выбрать…',self.pick)))
        form.addRow('Аргументы',self.args);form.addRow('Тайм-аут, с',self.timeout)
        form.addRow(label('Команда будет выполняться в отдельной копии проекта только после просмотра результата и подтверждения прав.'))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Добавить');buttons.button(QDialogButtonBox.Cancel).setText('Отмена')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);form.addRow(buttons)
    def pick(self):
        path,_=QFileDialog.getOpenFileName(self,'Программа проверки')
        if path:self.executable.setText(path)
    def value(self):
        return {'name':self.name.text().strip(),'kind':self.kind.currentText(),
            'argv':[self.executable.text().strip(),*self.args.toPlainText().splitlines()],
            'timeout':self.timeout.value(),'approved':True}


class MissionDialog(QDialog):
    def __init__(self,jobs,preferences,models,parent=None,existing=None):
        super().__init__(parent);self.setWindowTitle('Изменить задание' if existing else 'Новое задание')
        self.resize(740,760);self.existing=existing;self.commands=[];self.models=models
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True)
        body=QWidget();form=QFormLayout(body);form.setSpacing(12);scroll.setWidget(body);outer.addWidget(scroll)
        self.title=QLineEdit();self.description=QPlainTextEdit();self.description.setMinimumHeight(100)
        self.description.setPlaceholderText('Опишите нужный результат обычным языком')
        self.project=QLineEdit();self.project.setReadOnly(True)
        self.kind=QComboBox();self.kind.addItems(['Изменения в проекте','Текст с точным ожидаемым ответом'])
        self.priority=QSpinBox();self.priority.setRange(-100,100)
        self.mode=QComboBox();self.mode.addItems(['economy','balanced','quality','manual']);self.mode.setCurrentText(preferences.get('mode','balanced'))
        self.model=QComboBox();self.effort=QComboBox()
        for m in models:self.model.addItem(m.get('displayName') or m['model'],m['model'])
        self.model.currentIndexChanged.connect(self.refresh_efforts);self.refresh_efforts()
        self.mode.currentTextChanged.connect(lambda:self.update_manual());self.update_manual()
        self.policy=QComboBox();self.policy.addItems(['balanced','weekly','reserve','stop']);self.policy.setCurrentText(preferences.get('policy','balanced'))
        self.budget=QSpinBox();self.budget.setRange(1,8);self.budget.setValue(preferences.get('maxAttempts',3))
        self.turn_timeout=QSpinBox();self.turn_timeout.setRange(10,86400);self.turn_timeout.setValue(600)
        self.dependencies=QListWidget();self.dependencies.setMaximumHeight(100)
        for job in jobs:
            if existing and job['id']==existing['id']:continue
            item=QListWidgetItem(job['title']+' ('+job['id']+')');item.setData(Qt.UserRole,job['id'])
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Unchecked);self.dependencies.addItem(item)
        self.inputs=QPlainTextEdit();self.inputs.setMaximumHeight(75);self.inputs.setPlaceholderText('Явно выбранные файлы контекста')
        self.writes=QPlainTextEdit();self.writes.setMaximumHeight(75);self.writes.setPlaceholderText('Разрешённые относительные имена, по одному на строку')
        self.checks=QListWidget();self.checks.setMaximumHeight(85)
        self.expected=QLineEdit();self.expected.setPlaceholderText('Точное содержимое ответа для текстового задания')
        for title,widget in [('Название',self.title),('Задача',self.description),('Проект',row(self.project,button('Папка…',self.pick_project))),
            ('Результат',self.kind),('Приоритет',self.priority),('Стратегия',self.mode),('Модель',self.model),('Reasoning effort',self.effort),
            ('Политика лимитов',self.policy),('Максимум попыток',self.budget),('Тайм-аут ответа, с',self.turn_timeout),('Зависимости',self.dependencies),
            ('Файлы контекста',self.inputs),('',button('Выбрать файлы…',self.pick_inputs)),('Разрешено менять',self.writes),
            ('Проверки',self.checks),('',row(button('Добавить проверку…',self.add_command),button('Удалить проверку',self.remove_command))),('Ожидаемый текст',self.expected)]:form.addRow(title,widget)
        form.addRow(label('Проект не перезаписывается: результат остаётся в частной рабочей копии. Для проекта нужны явные файлы и хотя бы одна проверка.'))
        self.error=label();outer.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Сохранить');buttons.button(QDialogButtonBox.Cancel).setText('Отмена')
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);outer.addWidget(buttons)
        if existing:self.load(existing)

    def refresh_efforts(self):
        self.effort.clear();m=next((m for m in self.models if m['model']==self.model.currentData()),None)
        if m:self.effort.addItems([x['reasoningEffort'] for x in m.get('supportedReasoningEfforts',[])])
    def update_manual(self):
        manual=self.mode.currentText()=='manual';self.model.setEnabled(manual);self.effort.setEnabled(manual)
    def pick_project(self):
        path=QFileDialog.getExistingDirectory(self,'Выберите проект',self.project.text())
        if path:self.project.setText(path)
    def pick_inputs(self):
        if not self.project.text():self.pick_project()
        if not self.project.text():return
        paths,_=QFileDialog.getOpenFileNames(self,'Файлы контекста',self.project.text())
        try:
            values=[Path(p).resolve().relative_to(Path(self.project.text()).resolve()).as_posix() for p in paths]
            prior=self.inputs.toPlainText().splitlines();self.inputs.setPlainText('\n'.join(dict.fromkeys(prior+values)))
        except ValueError:self.error.setText('Выберите файлы внутри выбранного проекта')
    def add_command(self):
        dialog=CommandDialog(self)
        if dialog.exec()==QDialog.Accepted:
            self.commands.append(dialog.value());self.render_commands()
    def remove_command(self):
        index=self.checks.currentRow()
        if index>=0:self.commands.pop(index);self.render_commands()
    def render_commands(self):
        self.checks.clear();self.checks.addItems([c['name']+': '+str(c['argv']) for c in self.commands])
    def load(self,job):
        self.title.setText(job['title']);self.description.setPlainText(job['task']['text']);self.project.setText(job['project'])
        self.priority.setValue(job['priority']);self.mode.setCurrentText('manual' if job.get('manual') else job['mode'])
        self.budget.setValue(job['maxAttempts']);self.turn_timeout.setValue(int(job.get('turnTimeout',120)))
        self.policy.setCurrentText(job.get('policy',{}).get('mode','balanced'))
        for i in range(self.dependencies.count()):
            item=self.dependencies.item(i);item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in job['dependsOn'] else Qt.Unchecked)
        if job['type']=='text':self.kind.setCurrentIndex(1);self.expected.setText(job['expected'])
        else:
            self.inputs.setPlainText('\n'.join(job['criteria']['inputFiles']));self.writes.setPlainText('\n'.join(job['criteria']['writeFiles']))
            self.commands=job['criteria']['commands'].copy();self.render_commands()
        if job.get('manual'):
            self.model.setCurrentIndex(self.model.findData(job['manual']['model']));self.effort.setCurrentText(job['manual']['effort'])
    def definition(self):
        mode=self.mode.currentText();project=self.project.text()
        prior=self.existing or {}
        job={'id':self.existing['id'] if self.existing else 'mission-'+uuid.uuid4().hex[:12],
            'title':self.title.text().strip(),'project':project,'task':{**prior.get('task',{}),'text':self.description.toPlainText()},
            'type':'project' if self.kind.currentIndex()==0 else 'text','priority':self.priority.value(),
            'mode':'balanced' if mode=='manual' else mode,'maxAttempts':self.budget.value(),
            'turnTimeout':self.turn_timeout.value(),'policy':{**prior.get('policy',{}),'mode':self.policy.currentText()},
            'dependsOn':[self.dependencies.item(i).data(Qt.UserRole) for i in range(self.dependencies.count()) if self.dependencies.item(i).checkState()==Qt.Checked]}
        if mode=='manual':job['manual']={'model':self.model.currentData(),'effort':self.effort.currentText()}
        if job['type']=='text':job['expected']=self.expected.text()
        else:
            job['criteria']={**prior.get('criteria',{}),'project':project,'inputFiles':self.inputs.toPlainText().splitlines(),
            'writeFiles':self.writes.toPlainText().splitlines(),'commands':self.commands}
        return job
    def save(self):
        from ..queue import MissionQueue
        from ..safety import reject_secrets
        try:
            value=self.definition();MissionQueue(Path('unused.sqlite3'))._definition(value);reject_secrets(value)
            if value.get('manual') and (not value['manual']['model'] or not value['manual']['effort']):raise ValueError('Подключите Codex и выберите доступную модель')
            self.accept()
        except (ValueError,KeyError,TypeError) as error:self.error.setText(str(error))


class MissionsPage(QWidget):
    def __init__(self,bridge,parent=None):
        super().__init__(parent);self.bridge=bridge;self.data={};self.jobs=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12);layout.addWidget(label('Центр миссий','title'))
        self.queue_state=label('Очередь пуста','muted');layout.addWidget(self.queue_state)
        self.add_button=button('Добавить задачу',lambda:self.edit(),True)
        self.edit_button=button('Изменить',lambda:self.edit(self.selected()))
        self.access_button=button('Разрешения…',self.access)
        self.pause_button=button('Пауза',lambda:self.control('pause'))
        self.resume_button=button('Продолжить',lambda:self.control('resume'))
        self.cancel_button=button('Отменить',self.cancel)
        layout.addLayout(row(self.add_button,self.edit_button,self.access_button))
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['Задание','Статус','Приоритет','Модель','Время','Попытки','Зависимости'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.verticalHeader().hide()
        self.table.setAccessibleName('Очередь миссий');self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(42);self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.update_actions);layout.addWidget(self.table,1)
        self.empty_state=label('Начните с новой миссии\nОпишите результат, выберите проект и проверки. После просмотра разрешений миссия будет готова к запуску.','section')
        self.empty_state.setAlignment(Qt.AlignCenter);layout.addWidget(self.empty_state,1)
        self.retry_button=button('Повторить проверенное',lambda:self.control('retry'))
        self.ack_button=button('Разобрать неопределённый результат…',self.acknowledge)
        self.result_button=button('Результат и история',self.result)
        layout.addLayout(row(self.pause_button,self.resume_button,self.cancel_button))
        layout.addLayout(row(self.result_button,self.retry_button))
        layout.addWidget(self.ack_button)
        self.summary=label('Выберите задание','muted');layout.addWidget(self.summary);self.update_actions()
    def selected(self):
        index=self.table.currentRow();return self.jobs[index] if 0<=index<len(self.jobs) else None
    def update_data(self,data):
        identity=(self.selected() or {}).get('id');self.data=data;self.jobs=data['missions']
        self.empty_state.setVisible(not self.jobs)
        self.table.setVisible(bool(self.jobs))
        self.queue_state.setText(f'Миссий: {len(self.jobs)} · активная: '+('есть' if data.get('active') else 'нет')+(' · очередь на паузе' if data.get('paused') else '') if self.jobs else 'Очередь пуста · добавьте первую миссию')
        self.table.blockSignals(True);self.table.setRowCount(len(self.jobs))
        selected=-1
        for i,j in enumerate(self.jobs):
            if j['id']==identity:selected=i
            decision=j.get('live',{}).get('decision') or j.get('model') or {}
            values=[j['title'],STATUS.get(j['status'],j['status']),str(j['priority']),decision.get('model','—'),duration(j),
                str(len(j.get('live',{}).get('attempts') or j.get('attempts',[]))),', '.join(j['dependsOn']) or '—']
            for col,value in enumerate(values):self.table.setItem(i,col,QTableWidgetItem(value))
        if selected>=0:self.table.selectRow(selected)
        self.table.blockSignals(False);self.update_actions()
    def update_actions(self):
        job=self.selected();status=job['status'] if job else None
        terminal=status in {'completed','cancelled','failed','needs_attention'}
        self.edit_button.setEnabled(bool(job and status in {'pending','paused'} and not job['dispatchStarted']))
        self.access_button.setEnabled(bool(job and not self.data.get('active')))
        self.pause_button.setEnabled(bool(job and not terminal and status!='paused'))
        self.resume_button.setEnabled(status=='paused')
        self.cancel_button.setEnabled(bool(job and status not in {'completed','failed','needs_attention','cancelled'}))
        attempts=(job or {}).get('attempts',[]);last=attempts[-1] if attempts else {}
        uncertain=last.get('validation',{}).get('kind')=='not_retryable'
        used=len(attempts)+sum(x['count'] for x in (job or {}).get('archives',[]))
        retryable=bool(job and status=='failed' and last.get('phase')=='validated' and
            last.get('validation',{}).get('passed') is False and used<job['maxAttempts'] and self.data.get('active')!=job['id'])
        self.retry_button.setEnabled(retryable and not uncertain)
        self.result_button.setEnabled(bool(job))
        self.ack_button.setEnabled(bool(job and (uncertain or status=='needs_attention')))
        message='Выберите задание'
        if job:
            message=job.get('stopReason') or job.get('live',{}).get('stopReason') or (
                'Ожидает завершения: '+', '.join(job['dependsOn']) if job['dependsOn'] else 'Выберите действие для задания')
        self.summary.setText(message)
    def edit(self,job=None):
        dialog=MissionDialog(self.jobs,self.data.get('preferences',{}),self.data.get('models',[]),self,existing=job)
        if dialog.exec()==QDialog.Accepted:
            if job:self.bridge.request('edit',identity=job['id'],definition=dialog.definition())
            else:self.bridge.request('add',definition=dialog.definition())
    def control(self,action,**values):
        job=self.selected()
        if job:
            if action=='resume':self.bridge.request('resume_mission',identity=job['id'])
            else:self.bridge.request('control',action=action,identity=job['id'],**values)
    def cancel(self):
        if QMessageBox.question(self,'Отмена','Остановить это задание? Уже отправленный запрос может потребовать восстановления.')==QMessageBox.Yes:self.control('cancel')
    def access(self):
        job=self.selected()
        if job:self.bridge.request('access_review',identity=job['id'])
    def result(self):
        job=self.selected()
        if job:self.bridge.request('result',identity=job['id'])
    def acknowledge(self):
        job=self.selected()
        if not job:return
        self.bridge.request('result',identity=job['id'])
        # Actual acknowledgement is a separate dialog after evidence has loaded.
