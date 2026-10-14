"""Concept C project planning. Draft proposals never dispatch or approve code."""
import json
import uuid
from html import escape
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QHeaderView, QAbstractItemView
from .localized_widgets import (QDialog, QComboBox, QLineEdit, QPlainTextEdit,
    QFormLayout, QCheckBox, QListWidget, QTableWidget, QTableWidgetItem, QFileDialog, set_text)
from .i18n import tr, join_text, format_text, manager, message_text
from .widgets import label, button, plain, row, STATUS


def plan_sections(value):
    nodes=(value.get('draft') or {}).get('missions',[])
    plan=[value['title'],value['goal'],tr('Проект: ')+value['project']]
    files=[];commands=[]
    for node in nodes:
        heading=node['id']+' · '+node['title']
        plan += [heading,node['stage'],node['task'],tr('Зависимости: ')+(', '.join(node['dependsOn']) or tr('Нет'))]
        files += [heading,tr('Файлы контекста:\n')+'\n'.join(node['inputFiles']),
                  tr('Разрешено менять:\n')+'\n'.join(node['writeFiles'])]
        commands += [heading]+[c['name']+' · '+c['kind']+'\n'+json.dumps(c['argv'],ensure_ascii=False)+'\n'+
            tr('Тайм-аут, с')+': '+str(c['timeout']) for c in node['commands']]
    return [(tr('План проекта'),join_text('\n\n',plan)),
            (tr('Файлы и границы доступа'),join_text('\n\n',[tr('Проект: ')+value['project'],*files])),
            (tr('Предложенные команды'),join_text('\n\n',commands)),
            (tr('Раздельные подтверждения'),tr('Подтверждение создаст миссии с указанными файлами и командами. Оно не расширяет разрешённые корни, не запускает очередь и не разрешает исполнение кода. Для каждой миссии нужны отдельное разрешение доступа и подтверждение конкретного результата.'))]


class PlanReviewDialog(QDialog):
    def __init__(self,value,bridge,parent=None):
        super().__init__(parent);self.value=value;self.bridge=bridge;self.viewed=set();self.stale=False;self.busy=False
        self.setWindowTitle(tr('Подтвердить план и полномочия'));self.resize(800,600)
        layout=QVBoxLayout(self);layout.addWidget(label(tr('Черновик Codex · проверка владельцем'),'section'))
        layout.addWidget(label(tr('Просмотрите каждый раздел. Команды пока не разрешены к исполнению.'),'warning'))
        split=QHBoxLayout();self.sections=QListWidget();self.sections.setMaximumWidth(230)
        self.sections.setAccessibleName(tr('Обязательные разделы просмотра'))
        self.viewer=plain();self.viewer.setAccessibleName(tr('Содержимое плана проекта'))
        split.addWidget(self.sections);split.addWidget(self.viewer,1);layout.addLayout(split,1)
        self.read_button=button(tr('Раздел просмотрен'),self.mark_viewed);layout.addWidget(self.read_button)
        self.progress=label('','muted');layout.addWidget(self.progress)
        self.consent=QCheckBox(tr('Я проверил план, каждый путь и команду и подтверждаю эти полномочия миссий'))
        layout.addWidget(self.consent)
        self.approve_button=button(tr('Подтвердить план и создать миссии'),self.approve,True)
        layout.addLayout(row(self.approve_button,button(tr('Закрыть'),self.reject)))
        self.sections.currentRowChanged.connect(self.show_section)
        self.consent.stateChanged.connect(self.update_ready)
        self.viewer.verticalScrollBar().valueChanged.connect(self.update_ready)
        self.viewer.verticalScrollBar().rangeChanged.connect(self.update_ready)
        self.bridge.snapshot.connect(self.snapshot);self.bridge.result.connect(self.result);self.bridge.error.connect(self.error)
        manager.changed.connect(self.retranslate);self.retranslate();self.update_ready()

    def retranslate(self,*_):
        selected=max(0,self.sections.currentRow());self.contents=plan_sections(self.value)
        with QSignalBlocker(self.sections):
            self.sections.clear();self.sections.addItems([str(title) for title,_ in self.contents]);self.sections.setCurrentRow(selected)
        self.show_section(selected)

    def show_section(self,index):
        if 0<=index<len(self.contents):self.viewer.setPlainText(self.contents[index][1]);self.update_ready()

    def mark_viewed(self):
        bar=self.viewer.verticalScrollBar()
        if not self.stale and bar.value()>=bar.maximum():self.viewed.add(self.sections.currentRow())
        self.update_ready()

    def update_ready(self,*_):
        self.read_button.setEnabled(not self.stale and not self.busy and self.viewer.verticalScrollBar().value()>=self.viewer.verticalScrollBar().maximum())
        self.approve_button.setEnabled(not self.stale and not self.busy and self.consent.isChecked() and len(self.viewed)==len(getattr(self,'contents',[])))
        set_text(self.progress,'setText',tr('План изменился. Откройте новый просмотр.') if self.stale else
                 format_text([tr('Просмотрено '),str(len(self.viewed)),tr(' из '),str(len(getattr(self,'contents',[]))),tr(' разделов и файлов')]))

    def approve(self):
        if not self.approve_button.isEnabled():return
        self.busy=True;self.update_ready()
        self.bridge.request('confirm_project_plan',identity=self.value['id'],review_id=self.value['reviewId'],acknowledge=True)

    def snapshot(self,data):
        if self.busy:return
        current=next((p for p in data.get('projects',[]) if p['id']==self.value['id']),None)
        if current is None or current['revision']!=self.value['revision'] or current.get('activated') or current.get('reviewId')!=self.value['reviewId']:
            self.stale=True;self.viewed.clear();self.consent.setChecked(False);self.update_ready()

    def result(self,action,value):
        if self.busy and action=='confirm_project_plan' and value.get('id')==self.value['id']:self.accept()

    def error(self,*_):
        if self.busy:self.busy=False;self.stale=True;self.consent.setChecked(False);self.update_ready()


class NewProjectDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle(tr('Новый проект'));self.resize(600,440)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.title=QLineEdit();self.goal=QPlainTextEdit();self.root=QLineEdit();self.inputs=QPlainTextEdit()
        self.root.setReadOnly(True);self.goal.setMaximumHeight(100);self.inputs.setMaximumHeight(85)
        self.inputs.setPlaceholderText(tr('Относительные пути, по одному на строку. Только выбранные файлы попадут в контекст планирования.'))
        form.addRow(tr('Название'),self.title);form.addRow(tr('Цель проекта'),self.goal)
        form.addRow(tr('Папка проекта'),row(self.root,button(tr('Выбрать…'),self.pick)))
        form.addRow(tr('Файлы контекста'),self.inputs)
        layout.addWidget(label(tr('Создание проекта сохраняет цель. Планирование требует отдельного разрешения миссии и запуска общей очереди.'),'muted'))
        self.validation=label('','warning');layout.addWidget(self.validation)
        layout.addLayout(row(button(tr('Создать проект'),self.submit,True),button(tr('Отмена'),self.reject)))
    def submit(self):
        from ..orchestration import check_context,text
        from ..safety import reject_secrets
        value=self.value()
        try:
            text(value['title']);text(value['goal']);reject_secrets(value)
            check_context({'project':value['project'],'inputFiles':value['input_files']})
        except ValueError as error:self.validation.setText(message_text(str(error)));return
        self.accept()
    def pick(self):
        path=QFileDialog.getExistingDirectory(self,tr('Папка проекта'))
        if path:self.root.setText(path)
    def value(self):
        return {'identity':'p-'+uuid.uuid4().hex[:12],'title':self.title.text(),'goal':self.goal.toPlainText(),
                'project':self.root.text(),'input_files':[n.strip() for n in self.inputs.toPlainText().splitlines() if n.strip()]}


class ProjectsDialog(QDialog):
    def __init__(self,bridge,data,parent=None):
        super().__init__(parent);self.bridge=bridge;self.data={};self.busy=False;self.editor_revision=None
        self.setWindowTitle(tr('Проекты'));self.resize(960,740)
        layout=QVBoxLayout(self);layout.addWidget(label(tr('Проекты · план, зависимости и прогресс'),'title'))
        self.selector=QComboBox();self.selector.setAccessibleName(tr('Выбрать проект'))
        layout.addLayout(row(self.selector,button(tr('Новый проект'),self.create)))
        self.summary=label('','muted');layout.addWidget(self.summary)
        self.request_button=button(tr('Запросить черновик Codex'),self.request_plan)
        self.review_button=button(tr('Просмотреть план и полномочия'),self.review,True)
        layout.addLayout(row(self.request_button,self.review_button))
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels([tr('Этап'),tr('Задание'),tr('Статус'),tr('Зависимости'),tr('Причина блокировки')])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Interactive)
        self.table.setColumnWidth(1,220);self.table.setMinimumHeight(100)
        layout.addWidget(self.table,1)
        self.details=plain();self.details.setMinimumHeight(90);layout.addWidget(self.details,1)
        layout.addLayout(row(button(tr('Разрешения выбранной миссии'),self.access),button(tr('Открыть миссии'),self.accept)))
        self.editor=QPlainTextEdit();self.editor.setAccessibleName(tr('Черновик плана JSON'))
        self.editor.setPlaceholderText(tr('Черновик плана JSON'));self.editor.setMinimumHeight(70);layout.addWidget(self.editor,1)
        self.save_button=button(tr('Сохранить изменения черновика'),self.save)
        layout.addLayout(row(self.save_button,button(tr('Закрыть'),self.reject)))
        self.notice=label(tr('Изменение утверждённого плана отзывает его полномочия. Отправленные миссии менять нельзя.'),'warning');layout.addWidget(self.notice)
        self.selector.currentIndexChanged.connect(self.render);self.table.itemSelectionChanged.connect(self.show_node)
        self.bridge.snapshot.connect(self.update_data);self.bridge.result.connect(self.result);self.bridge.error.connect(self.error)
        manager.changed.connect(self.render);self.update_data(data)

    def selected(self):return self.selector.currentData()

    def update_data(self,data):
        selected=self.selected();self.data=data
        with QSignalBlocker(self.selector):
            self.selector.clear()
            for project in data.get('projects',[]):self.selector.addItem(project['title'],project['id'])
            index=self.selector.findData(selected)
            if index>=0:self.selector.setCurrentIndex(index)
        self.render()

    def current(self):return next((p for p in self.data.get('projects',[]) if p['id']==self.selected()),None)

    def render(self,*_):
        selected_node=None
        index=self.table.currentRow()
        if 0<=index<len(getattr(self,'nodes',[])):selected_node=self.nodes[index]['id']
        project=self.current();self.table.setRowCount(0);self.selector.setEnabled(not self.busy)
        self.request_button.setEnabled(bool(project and not project.get('planner') and not project.get('draft') and not project.get('activated') and not self.busy))
        self.review_button.setEnabled(bool(project and project.get('draft') and not project.get('activated') and not self.busy))
        self.save_button.setEnabled(bool(project and not self.busy))
        if not project:self.summary.setText(tr('Создайте проект из общей цели.'));return
        state=tr('План подтверждён') if project.get('activated') else STATUS.get(project.get('planningStatus'),tr('Черновик'))
        self.summary.setText(format_text([project['goal'],'\n',str(project.get('completed',0)),' / ',str(project.get('total',0)),
            ' · ',state,' · ',tr('Очередь на паузе') if project.get('queuePaused') else tr('Общая очередь')]))
        revision=(project['id'],project['revision'],project.get('activated'))
        if self.editor_revision!=revision:
            self.editor.setPlainText(json.dumps(project.get('draft'),ensure_ascii=False,indent=2) if project.get('draft') else '')
            self.editor_revision=revision
        nodes=(project.get('draft') or {}).get('missions',[]);runtime={j['id']:j for j in project.get('missions',[])}
        self.nodes=nodes;self.table.setRowCount(len(nodes))
        for index,node in enumerate(nodes):
            job=runtime.get(project['id']+'-'+node['id'],{})
            reasons=[d['dependency']+' · '+str(STATUS.get(d['status'],d['status'])) for d in job.get('blockedBy',[])]
            if job.get('accessRequired'):reasons.append(str(tr('Нужно разрешение доступа')))
            if job.get('stopReason'):reasons.append(str(message_text(job['stopReason'])))
            values=[node['stage'],node['title'],STATUS.get(job.get('state') or job.get('status'),tr('Черновик')),', '.join(node['dependsOn']),'; '.join(reasons)]
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setToolTip('<qt>'+escape(str(value)).replace('\n','<br/>')+'</qt>');self.table.setItem(index,column,item)
        if nodes:self.table.selectRow(next((i for i,n in enumerate(nodes) if n['id']==selected_node),0))
        else:self.details.setPlainText(tr('План ещё не получен. Черновик можно запросить или вставить в JSON-редактор.'))

    def show_node(self):
        index=self.table.currentRow();project=self.current()
        if project and 0<=index<len(getattr(self,'nodes',[])):
            value={**project,'draft':{'missions':[self.nodes[index]]}}
            self.details.setPlainText(join_text('\n\n',[body for _,body in plan_sections(value)]))

    def create(self):
        dialog=NewProjectDialog(self)
        if dialog.exec()==QDialog.Accepted:self.send('create_project',**dialog.value())

    def send(self,action,**values):
        if self.busy:return
        self.pending=(action,values.get('identity'));self.busy=True;self.render();self.bridge.request(action,**values)

    def request_plan(self):
        if self.selected():self.send('request_project_plan',identity=self.selected())

    def review(self):
        if self.selected():self.send('review_project_plan',identity=self.selected())

    def save(self):
        project=self.current()
        if project:
            from ..orchestration import parse_plan
            try:plan=parse_plan(self.editor.toPlainText(),project['project'])
            except ValueError as error:self.notice.setText(message_text(str(error)));return
            self.send('save_project_plan',identity=project['id'],plan=plan,revision=project['revision'])

    def access(self):
        project=self.current();index=self.table.currentRow()
        identity=project['id']+'-'+self.nodes[index]['id'] if project and 0<=index<len(getattr(self,'nodes',[])) and project.get('activated') else project.get('planner') if project else None
        if identity:self.accept();self.bridge.request('access_review',identity=identity)

    def result(self,action,value):
        expected=getattr(self,'pending',None)
        if not self.busy or not expected or action!=expected[0]:return
        identity=expected[1]+'-plan' if action=='request_project_plan' else expected[1]
        if value.get('id')!=identity:return
        self.busy=False;self.render()
        if action=='review_project_plan':
            dialog=PlanReviewDialog(value,self.bridge,self);dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.open()

    def error(self,message):
        self.busy=False;self.notice.setText(message_text(message));self.render()
