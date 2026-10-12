from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text
from .localized_widgets import QWidget, QComboBox, set_text
from PySide6.QtWidgets import QVBoxLayout
from .widgets import label,button,row,plain,panel


class RouterPage(QWidget):
    def __init__(self,bridge):
        super().__init__();self.bridge=bridge;self.models=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16)
        layout.addWidget(label(tr('Маршрутизация моделей'),'title'))
        layout.addWidget(label(tr('Каждая новая задача получает собственную оценку сложности. Результаты проверок могут повысить модель в автоматическом режиме.'),'muted'))
        strategy,strategy_layout=panel(tr('01 · Стратегия новых миссий'))
        self.mode=QComboBox();self.mode.setAccessibleName(tr('Стратегия новых миссий'))
        for title,value in [(tr('Economy — беречь лимиты'),'economy'),(tr('Balanced — баланс'),'balanced'),(tr('Quality — качество'),'quality')]:self.mode.addItem(title,value)
        strategy_layout.addLayout(row(self.mode,button(tr('Применить к новым задачам'),lambda:bridge.request('save_preferences',values={'mode':self.mode.currentData()}),True)))
        strategy_layout.addWidget(label(tr('Ручной режим выбирается в редакторе задачи. Он сохраняет конкретную модель и effort, без автоматической эскалации.'),'muted'))
        layout.addWidget(strategy)
        catalog,catalog_layout=panel(tr('02 · Доступный каталог Codex'))
        self.catalog_state=label(tr('Нет данных · подключите Codex для загрузки каталога'),'muted');catalog_layout.addWidget(self.catalog_state)
        self.catalog=QComboBox();self.effort=QComboBox();self.catalog.currentIndexChanged.connect(self.update_efforts)
        self.catalog.setAccessibleName(tr('Модель из каталога Codex'));self.effort.setAccessibleName(tr('Поддерживаемый reasoning effort'))
        catalog_layout.addLayout(row(self.catalog,self.effort,button(tr('Обновить каталог'),lambda:bridge.request('refresh_connection'))))
        self.model_detail=label(tr('Выберите модель, чтобы увидеть поддерживаемые уровни reasoning effort.'),'muted');catalog_layout.addWidget(self.model_detail)
        layout.addWidget(catalog)
        layout.addWidget(label(tr('03 · История реальных решений'),'section'));self.history=plain();self.history.setAccessibleName(tr('История решений маршрутизатора'));layout.addWidget(self.history,1)
    def update_efforts(self):
        self.effort.clear();model=next((m for m in self.models if m['model']==self.catalog.currentData()),None)
        if model:self.effort.addEnums([x['reasoningEffort'] for x in model.get('supportedReasoningEfforts',[])])
        self.effort.setEnabled(bool(model and self.effort.count()))
        if hasattr(self,'model_detail'):
            set_text(self.model_detail, 'setText', model.get('description') or 'ID: ' + model['model'] if model else tr('Нет данных о модели. Обновите подключение для загрузки каталога.'))
    def update_data(self,data):
        self.mode.setCurrentIndex(max(0,self.mode.findData(data['preferences'].get('mode','balanced'))))
        if self.models!=data['models']:
            previous=self.catalog.currentData();self.models=data['models'];self.catalog.clear()
            for m in self.models:self.catalog.addItem(m.get('displayName') or m['model'],m['model'])
            index=self.catalog.findData(previous)
            if index>=0:self.catalog.setCurrentIndex(index)
            self.update_efforts()
        self.catalog.setEnabled(bool(self.models))
        self.effort.setEnabled(bool(self.models and self.effort.count()))
        if not self.models:set_text(self.model_detail, 'setText', tr('Нет данных о модели. Обновите подключение для загрузки каталога.'))
        set_text(self.catalog_state, 'setText', format_text([tr('Моделей в текущем каталоге: '), format_value(len(self.models), -1, ''), tr(' · уровни effort получены из Codex')]) if self.models else tr('Нет данных · каталог Codex ещё не получен'))
        lines=[]
        for job in data['missions']:
            attempts=job.get('pastAttempts',[])+(job.get('live',{}).get('attempts') or job.get('attempts',[]))
            for i,a in enumerate(attempts,1):
                d=a['decision'];outcome=a.get('validation',{}).get('passed')
                lines.append(format_text([format_value(job['title'], -1, ''), tr(' · попытка '), format_value(i, -1, ''), '\n', format_value(d['model'], -1, ''), ' / ', format_value(enum_label(d['effort']), -1, ''), ' · ', format_value(enum_label(d.get('complexity','—').lower()), -1, ''), '\n', format_value(message_text(d.get('reason', '')), -1, ''), tr('\nПроверка: ')])+{True:tr('пройдена'),False:tr('не пройдена'),None:tr('нет результата')}[outcome])
        text=join_text('\n\n', lines) or tr('Решений пока нет. Каталог загружается из Codex.')
        if self.history.toPlainText()!=text:self.history.setPlainText(text)
