"""Read-only presentation of existing snapshots; no dispatch or policy changes."""
import math
import time
from .i18n import tr, message_text, join_text, enum_label
from .widgets import STATUS, format_time
from ..model_policy import allowed_efforts


def active_mission(data):
    return next((j for j in data.get('missions',[]) if j['id']==data.get('active')),None)


def control_state(data):
    jobs=data.get('missions',[]);active=active_mission(data) or {}
    phase=active.get('live',{}).get('stage') or active.get('status')
    if phase=='needs_attention' or any(j['status']=='needs_attention' for j in jobs):
        title=tr('Требуется разбор результата');detail=tr('Исход операции неизвестен. Проверьте журнал и внешние последствия перед новой попыткой.');severity='danger'
    elif phase=='waiting_approval' or any(j['status']=='waiting_approval' for j in jobs):
        title=tr('Нужно ваше подтверждение');detail=tr('Просмотрите изменения, команды и риски. Новый код не выполняется без отдельного согласия.');severity='warning'
    elif active.get('cancelRequested') and phase not in {'completed','failed','cancelled'}:
        title=tr('Отмена запрошена');detail=tr('Остановка сервером не подтверждена. Запрос может ещё выполняться; проверьте итоговый журнал.');severity='warning'
    elif data.get('paused') or active.get('pauseRequested'):
        title=tr('Очередь на паузе');detail=tr('Новые задания не запускаются. Уже отправленный ход может продолжаться до безопасной границы.');severity='warning'
    elif phase and phase.startswith('waiting_'):
        title=STATUS.get(phase,message_text(phase));detail=message_text(active.get('live',{}).get('waitReason') or tr('Контроллер ждёт доступности. Новая отправка пока заблокирована.'));severity='warning'
    elif active and data.get('workerRunning'):
        title=STATUS.get(phase,message_text(phase));detail=active.get('title','');severity='info'
    elif any(j['status']=='failed' for j in jobs):
        title=tr('Есть задачи с ошибками');detail=tr('Откройте результат и историю. Повтор доступен только после проверки условий безопасности.');severity='danger'
    elif data.get('connection',{}).get('status')!='connected':
        title=tr('Подключение не подтверждено');detail=tr('Подключите Codex, чтобы получить актуальные модели и лимиты. Задания можно подготовить заранее.');severity='warning'
    else:
        title=tr('Система готова');detail=tr('Создайте миссию или запустите разрешённую очередь. Выбор модели будет сохранён в истории.');severity='success'
    return dict(title=title,detail=detail,severity=severity)


def quota_freshness(data,now=None):
    observed=data.get('limitsObservedAt');now=time.time() if now is None else now
    if observed is None:return tr('Время достоверного обновления неизвестно'),'warning'
    if not isinstance(observed,(int,float)) or not math.isfinite(observed) or observed>now+60:
        return tr('Время наблюдения недостоверно'),'warning'
    if now-observed>300:return tr('Данные старше 5 минут · обновите лимиты'),'warning'
    return tr('Последнее чтение: ')+format_time(observed),'info'


def model_facts(data):
    active=active_mission(data) or {};decision=active.get('live',{}).get('decision') or active.get('model') or {}
    selected=decision.get('model');manual=active.get('mode')=='manual' or bool(active.get('manual'))
    policies=data.get('preferences',{}).get('modelPolicies',{});facts=[]
    for model in data.get('models',[]):
        identity=model['model'];supported=[x['reasoningEffort'] for x in model.get('supportedReasoningEfforts',[])]
        efforts=allowed_efforts(identity,supported,automatic=not manual,policy=policies)
        notes=[]
        if model.get('hidden'):notes.append(tr('Модель скрыта текущим каталогом'))
        if 'inputModalities' in model and 'text' not in model['inputModalities']:notes.append(tr('Текстовый ввод не поддерживается'))
        rule=policies.get(identity)
        if rule:
            notes.append(tr('Предел рассуждения: {effort}',effort=enum_label(rule['maxEffort'])))
            if not rule['automaticEnabled']:notes.append(tr('Автовыбор отключён владельцем'))
        if not efforts:notes.append(tr('Нет разрешённых уровней рассуждения для текущего режима'))
        available=not model.get('hidden') and ('inputModalities' not in model or 'text' in model['inputModalities']) and bool(efforts)
        chosen=identity==selected
        if chosen:notes.append(message_text(decision.get('reason') or tr('Причина выбора не сохранена')))
        elif available:notes.append(tr('Причина отказа от этой альтернативы не сохранена'))
        facts.append(dict(model=identity,title=model.get('displayName') or identity,chosen=chosen,
            available=available,efforts=efforts,notes=join_text('\n',notes)))
    if selected and not any(f['model']==selected for f in facts):
        facts.append(dict(model=selected,title=selected,chosen=True,available=False,efforts=[],
            notes=tr('Сохранённый выбор отсутствует в текущем каталоге. Новая доступность не подтверждена.')))
    return facts


def mission_details(job,jobs):
    if not job:return tr('Выберите миссию, чтобы увидеть зависимости и причины ожидания.')
    names={j['id']:j for j in jobs};lines=[]
    for identity in job.get('dependsOn',[]):
        dependency=names.get(identity)
        lines.append((dependency['title']+' · '+STATUS.get(dependency['status'],dependency['status'])) if dependency else identity+' · '+tr('Зависимость не найдена'))
    reason=job.get('live',{}).get('waitReason') or job.get('live',{}).get('stopReason') or job.get('stopReason')
    result=tr('Проект: ')+job.get('project','')+'\n'+tr('Зависимости: ')+(join_text('\n',lines) or tr('Нет'))
    if reason:result+='\n'+tr('Причина: ')+message_text(reason)
    if job.get('cancelRequested') and job['status']!='cancelled':result+='\n'+tr('Отмена запрошена; остановка ещё не подтверждена.')
    if job.get('pauseRequested') and job['status']!='paused':result+='\n'+tr('Пауза запрошена; отправленный ход может продолжаться.')
    return result
