from PySide6.QtWidgets import QWidget,QVBoxLayout,QComboBox
from .widgets import label,button,row,plain,panel


class RouterPage(QWidget):
    def __init__(self,bridge):
        super().__init__();self.bridge=bridge;self.models=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16)
        layout.addWidget(label('Маршрутизация моделей','title'))
        layout.addWidget(label('Каждая новая задача получает собственную оценку сложности. Результаты проверок могут повысить модель в автоматическом режиме.','muted'))
        strategy,strategy_layout=panel('01 · Стратегия новых миссий')
        self.mode=QComboBox();self.mode.setAccessibleName('Стратегия новых миссий')
        for title,value in [('Economy — беречь лимиты','economy'),('Balanced — баланс','balanced'),('Quality — качество','quality')]:self.mode.addItem(title,value)
        strategy_layout.addLayout(row(self.mode,button('Применить к новым задачам',lambda:bridge.request('save_preferences',values={'mode':self.mode.currentData()}),True)))
        strategy_layout.addWidget(label('Ручной режим выбирается в редакторе задачи. Он сохраняет конкретную модель и effort, без автоматической эскалации.','muted'))
        layout.addWidget(strategy)
        catalog,catalog_layout=panel('02 · Доступный каталог Codex')
        self.catalog_state=label('Нет данных · подключите Codex для загрузки каталога','muted');catalog_layout.addWidget(self.catalog_state)
        self.catalog=QComboBox();self.effort=QComboBox();self.catalog.currentIndexChanged.connect(self.update_efforts)
        self.catalog.setAccessibleName('Модель из каталога Codex');self.effort.setAccessibleName('Поддерживаемый reasoning effort')
        catalog_layout.addLayout(row(self.catalog,self.effort,button('Обновить каталог',lambda:bridge.request('refresh_connection'))))
        self.model_detail=label('Выберите модель, чтобы увидеть поддерживаемые уровни reasoning effort.','muted');catalog_layout.addWidget(self.model_detail)
        layout.addWidget(catalog)
        layout.addWidget(label('03 · История реальных решений','section'));self.history=plain();self.history.setAccessibleName('История решений маршрутизатора');layout.addWidget(self.history,1)
    def update_efforts(self):
        self.effort.clear();model=next((m for m in self.models if m['model']==self.catalog.currentData()),None)
        if model:self.effort.addItems([x['reasoningEffort'] for x in model.get('supportedReasoningEfforts',[])])
        self.effort.setEnabled(bool(model and self.effort.count()))
        if hasattr(self,'model_detail'):
            self.model_detail.setText((model.get('description') or 'ID: '+model['model']) if model else 'Нет данных о модели. Обновите подключение для загрузки каталога.')
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
        if not self.models:self.model_detail.setText('Нет данных о модели. Обновите подключение для загрузки каталога.')
        self.catalog_state.setText(f'Моделей в текущем каталоге: {len(self.models)} · уровни effort получены из Codex' if self.models else 'Нет данных · каталог Codex ещё не получен')
        lines=[]
        for job in data['missions']:
            attempts=job.get('pastAttempts',[])+(job.get('live',{}).get('attempts') or job.get('attempts',[]))
            for i,a in enumerate(attempts,1):
                d=a['decision'];outcome=a.get('validation',{}).get('passed')
                lines.append(f'{job["title"]} · попытка {i}\n{d["model"]} / {d["effort"]} · {d.get("complexity","—")}\n'
                    f'{d.get("reason","")}\nПроверка: '+{True:'пройдена',False:'не пройдена',None:'нет результата'}[outcome])
        text='\n\n'.join(lines) or 'Решений пока нет. Каталог загружается из Codex.'
        if self.history.toPlainText()!=text:self.history.setPlainText(text)
