"""Observed quotas and analytics; no estimated cost or fictional progress."""
from collections import Counter
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QComboBox,QHBoxLayout,QTableWidget,
    QTableWidgetItem,QHeaderView,QAbstractItemView)
from .widgets import label,button,row,plain,panel,limits_text,duration,format_time


POLICIES=[('balanced','Баланс — ожидание доступности'),('weekly','Сохранить недельный резерв (85%)'),
          ('reserve','Беречь оба окна (90%)'),('stop','Ожидать после порога 100%')]


class LimitsPage(QWidget):
    def __init__(self,bridge):
        super().__init__();layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16);layout.addWidget(label('Лимиты и доступность','title'))
        layout.addWidget(label('Оставшийся и использованный лимит — разные величины. При отсутствии достоверного недельного окна backend останавливает новые запросы.','muted'))
        windows=QHBoxLayout();self.window_labels={}
        for kind,title in [('five_hour','Окно · 5 часов'),('weekly','Окно · неделя')]:
            frame,body=panel(title);value=label('Нет данных','section');body.addWidget(value)
            self.window_labels[kind]=value;windows.addWidget(frame,1)
        layout.addLayout(windows)
        self.availability=label('Доступность не подтверждена: нет наблюдений Codex.','muted');layout.addWidget(self.availability)
        self.credits=label('Кредиты: нет данных','muted');layout.addWidget(self.credits)
        policy_frame,policy_layout=panel('Политика новых миссий')
        self.policy=QComboBox()
        for value,title in POLICIES:self.policy.addItem(title,value)
        policy_layout.addLayout(row(self.policy,button('Для новых задач',lambda:bridge.request('save_preferences',values={'policy':self.policy.currentData()})),
            button('Обновить лимиты',lambda:bridge.request('refresh_connection'))))
        policy_layout.addWidget(label('Во время ожидания действует сохранённая политика задания. Доступность проверяет Limit Manager с увеличивающимся интервалом.','muted'))
        layout.addWidget(policy_frame)
        layout.addWidget(label('Наблюдения и причины ожидания','section'))
        self.detail=plain();self.detail.setAccessibleName('Подробные наблюдения лимитов');layout.addWidget(self.detail,1)
    def update_data(self,data):
        active=next((j for j in data['missions'] if j['id']==data['active']),None)
        live=(active or {}).get('live',{})
        for kind,value in self.window_labels.items():
            observed={'windows':[w for w in data['limits'].get('windows',[]) if w['kind']==kind]}
            if observed['windows']:
                parts=[]
                for window in observed['windows']:
                    used=window.get('usedPercent');remaining=window.get('remainingPercent')
                    amount='Нет данных' if used is None or remaining is None else f'{remaining:g}% осталось · {used:g}% использовано'
                    parts.append(f'{window["limitId"]}: {amount}\nСброс: '+format_time(window.get('resetsAt')))
                value.setText('\n\n'.join(parts))
            else:value.setText('Нет данных\nОкно не получено от Codex')
        self.availability.setText('Последнее чтение: '+format_time(data.get('limitsObservedAt'))+' · '+data['connection']['message'])
        from .credit_policy import MODES
        credit=data['preferences'].get('creditPolicy',{})
        observations=data['limits'].get('credits',[])
        balances='; '.join(str(c.get('limitId'))+': '+str(c.get('balance') or 'баланс неизвестен')+
            ' · наличие: '+{True:'да',False:'нет',None:'неизвестно'}.get(c.get('hasCredits'),'неизвестно')
            for c in observations) or 'нет данных'
        self.credits.setText('Кредиты (единицы сервиса, не денежная оценка): '+balances+'\n'+
            dict(MODES).get(credit.get('mode','never'))+
            ' · резерв 5 ч: '+str(credit.get('fiveHourReserve',10))+'% · неделя: '+str(credit.get('weeklyReserve',10))+'%\n'+
            'Платное продолжение не поддерживается. Порог блокирует новые запросы; отсутствие списаний не гарантировано.')
        text=limits_text(data['limits'])+'\n\nПоследнее чтение: '+format_time(data.get('limitsObservedAt'))+'\n'+data['connection']['message']
        if live.get('stage','').startswith('waiting_'):
            text+='\n\nСостояние: '+live['stage']+'\nПричина: '+str(live.get('waitReason') or live.get('stopReason') or 'Нет данных')
            wake=live.get('nextCheckAt');text+='\nСледующая проверка: '+format_time(wake)
        if self.detail.toPlainText()!=text:self.detail.setPlainText(text)
        self.policy.setCurrentIndex(max(0,self.policy.findData(data['preferences'].get('policy','balanced'))))


class AnalyticsPage(QWidget):
    def __init__(self):
        super().__init__();layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16);layout.addWidget(label('Аналитика миссий','title'))
        layout.addWidget(label('Только сохранённые факты. Точная стоимость и экономия токенов недоступны.','muted'))
        metrics=QHBoxLayout();self.metrics={}
        for key,title in [('missions','Всего миссий'),('completed','Завершено'),('attempts','Попыток'),('attention','Требуют разбора')]:
            frame,body=panel(title);value=label('0','title');body.addWidget(value);self.metrics[key]=value;metrics.addWidget(frame,1)
        layout.addLayout(metrics)
        self.validation_summary=label('Проверок пока нет','muted');layout.addWidget(self.validation_summary)
        layout.addWidget(label('Распределение моделей · фактические попытки','section'))
        self.model_distribution=QTableWidget(0,2);self.model_distribution.setHorizontalHeaderLabels(['Модель','Попытки'])
        self.model_distribution.setEditTriggers(QAbstractItemView.NoEditTriggers);self.model_distribution.verticalHeader().hide()
        self.model_distribution.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.model_distribution.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents)
        self.model_distribution.setMaximumHeight(180);self.model_distribution.setAccessibleName('Фактическое распределение моделей')
        layout.addWidget(self.model_distribution)
        self.empty_state=label('Нет данных · статистика появится после первой попытки миссии.','muted');layout.addWidget(self.empty_state)
        layout.addWidget(label('Подробная история · миссии и лимиты','section'))
        self.detail=plain();layout.addWidget(self.detail,1)
    def update_data(self,data):
        jobs=data['missions'];states=Counter(j['status'] for j in jobs);models=Counter();passed=failed=waiting=0;attempt_count=0
        lines=[f'Миссий: {len(jobs)} · завершено: {states["completed"]} · ошибок: {states["failed"]} · требуют разбора: {states["needs_attention"]}']
        for job in jobs:
            attempts=job.get('pastAttempts',[])+(job.get('live',{}).get('attempts') or job.get('attempts',[]))
            attempt_count+=len(attempts)
            for a in attempts:
                models[a['decision']['model']]+=1
                result=a.get('validation',{}).get('passed')
                approval=a.get('validation',{}).get('kind')=='execution_approval_required'
                waiting+=approval;passed+=result is True;failed+=result is False and not approval
        lines.append(f'Сохранённые попытки: {attempt_count}\nПроверки пройдены: {passed} · не пройдены: {failed} · ожидают разрешения: {waiting}')
        for key,value in [('missions',len(jobs)),('completed',states['completed']),('attempts',attempt_count),('attention',states['needs_attention'])]:self.metrics[key].setText(str(value))
        self.validation_summary.setText(f'Проверки: {passed} пройдено · {failed} не пройдено · {waiting} ожидают разрешения')
        self.model_distribution.setRowCount(len(models))
        for index,(name,count) in enumerate(models.most_common()):
            self.model_distribution.setItem(index,0,QTableWidgetItem(name));self.model_distribution.setItem(index,1,QTableWidgetItem(str(count)))
        self.model_distribution.setVisible(bool(models));self.empty_state.setVisible(not models)
        lines.append('Выбор моделей (фактические попытки):\n'+('\n'.join(f'{name}: {count}' for name,count in models.most_common()) or 'Нет данных'))
        lines.append('Длительность и результаты:\n'+('\n'.join(j['title']+': '+duration(j)+' · '+j['status'] for j in jobs) or 'Нет данных'))
        history=data.get('limitHistory',[])
        observations=[]
        for item in history[-20:]:
            at=format_time(item['at'])
            observations.append(at+'\n'+limits_text(item))
        lines.append('История чтения лимитов (последние 20, всего хранится до 100):\n'+('\n\n'.join(observations) or 'Нет данных'))
        text='\n\n'.join(lines)
        if self.detail.toPlainText()!=text:self.detail.setPlainText(text)
