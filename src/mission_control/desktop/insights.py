"""Observed quotas and analytics; no estimated cost or fictional progress."""
from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text
from .localized_widgets import QWidget, QComboBox, QTableWidget, QTableWidgetItem, set_text
from collections import Counter
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QHeaderView, QAbstractItemView
from .widgets import label,button,row,plain,panel,limits_text,duration,format_time,STATUS
from .components import MetricStrip,severity
from .presentation import quota_freshness,active_mission


POLICIES=[('balanced',tr('Баланс — ожидание доступности')),('weekly',tr('Сохранить недельный резерв (85%)')),
          ('reserve',tr('Беречь оба окна (90%)')),('stop',tr('Ожидать после порога 100%'))]


class LimitsPage(QWidget):
    def __init__(self,bridge):
        super().__init__();layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16);layout.addWidget(label(tr('Лимиты и доступность'),'title'))
        layout.addWidget(label(tr('Оставшийся и использованный лимит — разные величины. При отсутствии достоверного недельного окна backend останавливает новые запросы.'),'muted'))
        windows=QHBoxLayout();self.window_labels={}
        for kind,title in [('five_hour',tr('Окно · 5 часов')),('weekly',tr('Окно · неделя'))]:
            frame,body=panel(title);value=label(tr('Нет данных'),'section');body.addWidget(value)
            self.window_labels[kind]=value;windows.addWidget(frame,1)
        layout.addLayout(windows)
        self.freshness=label('','muted');layout.addWidget(self.freshness)
        self.pause_state=label('','section');layout.addWidget(self.pause_state)
        self.availability=label(tr('Доступность не подтверждена: нет наблюдений Codex.'),'muted');layout.addWidget(self.availability)
        self.credits=label(tr('Кредиты: нет данных'),'muted');layout.addWidget(self.credits)
        policy_frame,policy_layout=panel(tr('Политика новых миссий'))
        self.policy=QComboBox()
        for value,title in POLICIES:self.policy.addItem(title,value)
        policy_layout.addLayout(row(self.policy,button(tr('Для новых задач'),lambda:bridge.request('save_preferences',values={'policy':self.policy.currentData()})),
            button(tr('Обновить лимиты'),lambda:bridge.request('refresh_connection'))))
        policy_layout.addWidget(label(tr('Во время ожидания действует сохранённая политика задания. Доступность проверяет Limit Manager с увеличивающимся интервалом.'),'muted'))
        layout.addWidget(policy_frame)
        layout.addWidget(label(tr('Наблюдения и причины ожидания'),'section'))
        self.detail=plain();self.detail.setAccessibleName(tr('Подробные наблюдения лимитов'));layout.addWidget(self.detail,1)
    def update_data(self,data):
        freshness,level=quota_freshness(data);set_text(self.freshness,'setText',freshness);severity(self.freshness,level)
        active=active_mission(data) or {};stage=active.get('live',{}).get('stage') or active.get('status','')
        from .presentation import control_state
        control=control_state(data)
        pause=control['title']+'\n'+control['detail']
        set_text(self.pause_state,'setText',pause)
        active=next((j for j in data['missions'] if j['id']==data['active']),None)
        live=(active or {}).get('live',{})
        for kind,value in self.window_labels.items():
            observed={'windows':[w for w in data['limits'].get('windows',[]) if w['kind']==kind]}
            if observed['windows']:
                parts=[]
                for window in observed['windows']:
                    used=window.get('usedPercent');remaining=window.get('remainingPercent')
                    amount=tr('Нет данных') if used is None or remaining is None else format_text([format_value(remaining, -1, format_text(['g'])), tr('% осталось · '), format_value(used, -1, format_text(['g'])), tr('% использовано')])
                    parts.append(format_text([format_value(window['limitId'], -1, ''), ': ', format_value(amount, -1, ''), tr('\nСброс: ')])+format_time(window.get('resetsAt')))
                set_text(value, 'setText', join_text('\n\n', parts))
            else:set_text(value, 'setText', tr('Нет данных\nОкно не получено от Codex'))
        set_text(self.availability, 'setText', tr('Последнее чтение: ') + format_time(data.get('limitsObservedAt')) + ' · ' + message_text(data['connection']['message']))
        from .credit_policy import MODES
        credit=data['preferences'].get('creditPolicy',{})
        observations=data['limits'].get('credits',[])
        balances=join_text('; ', (display(c.get('limitId')) + ': ' + display(c.get('balance') or tr('баланс неизвестен')) + tr(' · наличие: ') + {True: tr('да'), False: tr('нет'), None: tr('неизвестно')}.get(c.get('hasCredits'), tr('неизвестно')) for c in observations)) or tr('нет данных')
        set_text(self.credits, 'setText', tr('Кредиты (единицы сервиса, не денежная оценка): ') + balances + '\n' + dict(MODES).get(credit.get('mode', 'never')) + tr(' · резерв 5 ч: ') + display(credit.get('fiveHourReserve', 10)) + tr('% · неделя: ') + display(credit.get('weeklyReserve', 10)) + '%\n' + tr('Платное продолжение не поддерживается. Порог блокирует новые запросы; отсутствие списаний не гарантировано.'))
        text=limits_text(data['limits'])+tr('\n\nПоследнее чтение: ')+format_time(data.get('limitsObservedAt'))+'\n'+message_text(data['connection']['message'])
        if live.get('stage','').startswith('waiting_'):
            text+=tr('\n\nСостояние: ')+STATUS.get(live['stage'],message_text(live['stage']))+tr('\nПричина: ')+message_text(live.get('waitReason') or live.get('stopReason') or tr('Нет данных'))
            wake=live.get('nextCheckAt');text+=tr('\nСледующая проверка: ')+format_time(wake)
        if self.detail.toPlainText()!=text:self.detail.setPlainText(text)
        self.policy.setCurrentIndex(max(0,self.policy.findData(data['preferences'].get('policy','balanced'))))


class AnalyticsPage(QWidget):
    def __init__(self):
        super().__init__();layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16);layout.addWidget(label(tr('Аналитика миссий'),'title'))
        layout.addWidget(label(tr('Только сохранённые факты. Точная стоимость и экономия токенов недоступны.'),'muted'))
        metrics=MetricStrip([('missions',tr('Всего миссий')),('completed',tr('Завершено')),('attempts',tr('Попыток')),('attention',tr('Требуют разбора'))])
        self.metrics=metrics.values;layout.addWidget(metrics)
        self.validation_summary=label(tr('Проверок пока нет'),'muted');layout.addWidget(self.validation_summary)
        layout.addWidget(label(tr('Распределение моделей · фактические попытки'),'section'))
        self.model_distribution=QTableWidget(0,2);self.model_distribution.setHorizontalHeaderLabels([tr('Модель'),tr('Попытки')])
        self.model_distribution.setEditTriggers(QAbstractItemView.NoEditTriggers);self.model_distribution.verticalHeader().hide()
        self.model_distribution.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.model_distribution.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents)
        self.model_distribution.setMaximumHeight(180);self.model_distribution.setAccessibleName(tr('Фактическое распределение моделей'))
        layout.addWidget(self.model_distribution)
        self.empty_state=label(tr('Нет данных · статистика появится после первой попытки миссии.'),'muted');layout.addWidget(self.empty_state)
        layout.addWidget(label(tr('Подробная история · миссии и лимиты'),'section'))
        self.detail=plain();layout.addWidget(self.detail,1)
    def update_data(self,data):
        jobs=data['missions'];states=Counter(j['status'] for j in jobs);models=Counter();passed=failed=waiting=0;attempt_count=0
        lines=[format_text([tr('Миссий: '), format_value(len(jobs), -1, ''), tr(' · завершено: '), format_value(states['completed'], -1, ''), tr(' · ошибок: '), format_value(states['failed'], -1, ''), tr(' · требуют разбора: '), format_value(states['needs_attention'], -1, '')])]
        for job in jobs:
            attempts=job.get('pastAttempts',[])+(job.get('live',{}).get('attempts') or job.get('attempts',[]))
            attempt_count+=len(attempts)
            for a in attempts:
                models[a['decision']['model']]+=1
                result=a.get('validation',{}).get('passed')
                approval=a.get('validation',{}).get('kind')=='execution_approval_required'
                waiting+=approval;passed+=result is True;failed+=result is False and not approval
        lines.append(format_text([tr('Сохранённые попытки: '), format_value(attempt_count, -1, ''), tr('\nПроверки пройдены: '), format_value(passed, -1, ''), tr(' · не пройдены: '), format_value(failed, -1, ''), tr(' · ожидают разрешения: '), format_value(waiting, -1, '')]))
        for key,value in [('missions',len(jobs)),('completed',states['completed']),('attempts',attempt_count),('attention',states['needs_attention'])]:set_text(self.metrics[key], 'setText', display(value))
        set_text(self.validation_summary, 'setText', format_text([tr('Проверки: '), format_value(passed, -1, ''), tr(' пройдено · '), format_value(failed, -1, ''), tr(' не пройдено · '), format_value(waiting, -1, ''), tr(' ожидают разрешения')]))
        self.model_distribution.setRowCount(len(models))
        for index,(name,count) in enumerate(models.most_common()):
            self.model_distribution.setItem(index,0,QTableWidgetItem(name));self.model_distribution.setItem(index,1,QTableWidgetItem(display(count)))
        self.model_distribution.setVisible(bool(models));self.empty_state.setVisible(not models)
        lines.append(tr('Выбор моделей (фактические попытки):\n')+(join_text('\n', (format_text([format_value(name, -1, ''), ': ', format_value(count, -1, '')]) for name, count in models.most_common())) or tr('Нет данных')))
        lines.append(tr('Длительность и результаты:\n')+(join_text('\n', (j['title'] + ': ' + duration(j) + ' · ' + STATUS.get(j['status'],message_text(j['status'])) for j in jobs)) or tr('Нет данных')))
        history=data.get('limitHistory',[])
        observations=[]
        for item in history[-20:]:
            at=format_time(item['at'])
            observations.append(at+'\n'+limits_text(item))
        lines.append(tr('История чтения лимитов (последние 20, всего хранится до 100):\n')+(join_text('\n\n', observations) or tr('Нет данных')))
        text=join_text('\n\n', lines)
        if self.detail.toPlainText()!=text:self.detail.setPlainText(text)
