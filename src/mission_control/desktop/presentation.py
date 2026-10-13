"""Read-only presentation of existing snapshots; no dispatch or policy changes."""
import math
import time
from collections import Counter
from .i18n import tr, message_text, join_text, enum_label
from .widgets import STATUS, format_time
from ..model_policy import allowed_efforts


def active_mission(data):
    return next((j for j in data.get('missions',[]) if j['id']==data.get('active')),None)


def last_attempt(job):
    live=job.get('live') or {}
    attempts=live.get('attempts',job.get('attempts',[])) or []
    return attempts[-1] if attempts else {}


CHECKPOINT_STAGES={'waiting_resume','waiting_network','waiting_credit','waiting_limit','waiting_model'}


def checkpoint_pending(job):
    if (not job or job.get('cancelRequested') or job.get('status') in {'completed','cancelled','failed','needs_attention'}
            or (job.get('live') or {}).get('stage') not in CHECKPOINT_STAGES|{None}):return False
    return (last_attempt(job).get('phase')=='paused_turn' or
            (job.get('live') or {}).get('stage')=='waiting_resume' or job.get('status')=='waiting_resume')


def checkpoint_confirmed(attempt):
    receipt=attempt.get('pauseReceipt') or {};identity=attempt.get('turnId')
    return (attempt.get('phase')=='paused_turn' and isinstance(identity,str) and bool(identity)
            and receipt.get('turnId')==identity and bool(receipt.get('threadId'))
            and receipt.get('terminalConfirmed') is True
            and receipt.get('phase') in {'terminal_interrupted','terminal_completed'})


def checkpoint_needs_review(job):
    attempt=last_attempt(job)
    return checkpoint_pending(job) and (bool(job.get('pauseRequested')) or not checkpoint_confirmed(attempt) or
                                      attempt.get('continuationApproved')!=attempt['turnId'])


def turn_control_state(job):
    """Read persisted evidence; an ACK or a queue flag never proves termination."""
    live=job.get('live') or {};phase=live.get('stage') or job.get('status')
    attempt=last_attempt(job);receipt=attempt.get('pauseReceipt') or {};control=receipt.get('phase','')
    if checkpoint_pending(job):
        if not checkpoint_confirmed(attempt):
            return dict(code='outcome_unknown',title=tr('Требуется разбор результата'),
                        detail=tr('Подтверждение завершения хода отсутствует или не совпадает. Продолжение заблокировано.'),severity='danger')
        if attempt.get('continuationApproved')==attempt['turnId']:
            detail=tr('Согласие сохранено для точного turn ID. Перед новой отправкой контроллер проверит историю, лимиты и разрешения.')
            if job.get('pauseRequested'):detail=detail+'\n'+tr('Миссия на паузе. Откройте checkpoint для явного снятия паузы.')
            return dict(code='continuation_authorized',title=tr('Продолжение этого хода разрешено'),detail=detail,severity='info')
        return dict(code='checkpoint_review',title=tr('Ход завершён · просмотрите checkpoint'),
                    detail=tr('Откройте checkpoint и сверьте уже выполненные действия. Продолжение требует отдельного согласия на этот ход.'),severity='warning')
    if control and attempt.get('phase')=='submitted':
        if phase in {'waiting_network','waiting_active'}:
            return dict(code='outcome_unknown',title=tr('Исход остановки неизвестен'),
                        detail=tr('Нужна сверка с историей Codex. Неизвестные операции автоматически не повторяются.'),severity='danger')
        if 'unavailable_or_unknown' in control or control=='steer_mismatch':
            return dict(code='stop_unconfirmed',title=tr('Подтверждение остановки не получено'),
                        detail=tr('Исход запроса управления требует сверки. ACK не доказывает остановку процессов или отмену действий.'),severity='warning')
        if control.startswith('interrupt_'):
            return dict(code='interrupt_requested',title=tr('Запрос прерывания принят') if control=='interrupt_acknowledged' else tr('Запрошено прерывание'),
                        detail=tr('Завершение хода ещё не подтверждено. Уже выполненные действия не отменены.'),severity='warning')
        if control.startswith('steer_'):
            return dict(code='soft_stop_requested',title=tr('Запрошена мягкая остановка'),
                        detail=tr('Просим Codex завершить текущий шаг. Завершение хода ещё не подтверждено.'),severity='warning')
        if control.startswith('terminal_') and receipt.get('terminalConfirmed') is True:
            return dict(code='turn_ended',title=tr('Ход завершён · требуется сверка'),
                        detail=tr('Контроллер сохраняет итоговое состояние. До завершения сверки продолжение недоступно.'),severity='warning')
    if phase=='completed_unvalidated':
        return dict(code='turn_ended',title=tr('Ход завершён · проверка результата'),
                    detail=tr('Ответ получен. Проверка результата ещё не завершена.'),severity='info')
    return None


def control_state(data):
    jobs=data.get('missions',[]);active=active_mission(data) or {}
    phase=active.get('live',{}).get('stage') or active.get('status')
    code='idle';action=None;target=active.get('id')
    uncertain=next((j for j in jobs if j['status']=='needs_attention' or (j.get('live') or {}).get('stage')=='needs_attention'),None)
    checkpoint=next((j for j in ([active] if active else [])+jobs if checkpoint_pending(j)),None)
    turn_state=turn_control_state(active) if active else None
    if phase=='needs_attention' or uncertain:
        code='outcome_unknown';action='result';target=(uncertain or active).get('id')
        title=tr('Требуется разбор результата');detail=tr('Исход операции неизвестен. Проверьте журнал и внешние последствия перед новой попыткой.');severity='danger'
    elif turn_state and turn_state['code'] in {'outcome_unknown','stop_unconfirmed'}:
        return dict(turn_state,mission_id=target,action='result')
    elif phase=='waiting_approval' or any(j['status']=='waiting_approval' for j in jobs):
        code='execution_approval';action='approvals'
        target=next(j['id'] for j in jobs if j['status']=='waiting_approval' or (j.get('live') or {}).get('stage')=='waiting_approval')
        title=tr('Нужно ваше подтверждение');detail=tr('Просмотрите изменения, команды и риски. Новый код не выполняется без отдельного согласия.');severity='warning'
    elif checkpoint or turn_state:
        job=checkpoint or active;state=turn_control_state(job)
        if data.get('paused'):state['detail']=state['detail']+'\n'+tr('Очередь на паузе')
        return dict(state,mission_id=job['id'],action='checkpoint' if checkpoint_needs_review(job) else None)
    elif active.get('cancelRequested') and phase not in {'completed','failed','cancelled'}:
        title=tr('Отмена запрошена');detail=tr('Остановка сервером не подтверждена. Запрос может ещё выполняться; проверьте итоговый журнал.');severity='warning'
    elif data.get('paused') or active.get('pauseRequested'):
        code='pause_requested'
        title=tr('Очередь на паузе');detail=tr('Новые задания не запускаются. Уже отправленный ход может продолжаться до безопасной границы.');severity='warning'
    elif phase and phase.startswith('waiting_'):
        code='waiting'
        title=STATUS.get(phase,message_text(phase));detail=message_text(active.get('live',{}).get('waitReason') or tr('Контроллер ждёт доступности. Новая отправка пока заблокирована.'));severity='warning'
    elif phase=='auth_required':
        code='auth_required';title=tr('Требуется вход');detail=tr('Войдите в Codex');severity='warning'
    elif active and data.get('workerRunning'):
        code='running'
        title=STATUS.get(phase,message_text(phase));detail=active.get('title','');severity='info'
    elif any(j['status']=='failed' for j in jobs):
        action='result';target=next(j['id'] for j in jobs if j['status']=='failed')
        title=tr('Есть задачи с ошибками');detail=tr('Откройте результат и историю. Повтор доступен только после проверки условий безопасности.');severity='danger'
    elif data.get('connection',{}).get('status')!='connected':
        title=tr('Подключение не подтверждено');detail=tr('Подключите Codex, чтобы получить актуальные модели и лимиты. Задания можно подготовить заранее.');severity='warning'
    else:
        title=tr('Система готова');detail=tr('Создайте миссию или запустите разрешённую очередь. Выбор модели будет сохранён в истории.');severity='success'
    return dict(code=code,title=title,detail=detail,severity=severity,mission_id=target,action=action)


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
    counts=Counter(model['model'] for model in data.get('models',[]))
    for model in data.get('models',[]):
        identity=model['model'];supported=[x['reasoningEffort'] for x in model.get('supportedReasoningEfforts',[])]
        efforts=allowed_efforts(identity,supported,automatic=not manual,policy=policies)
        notes=[]
        if counts[identity]!=1:notes.append(tr('ID неоднозначен в текущем каталоге'))
        if model.get('hidden'):notes.append(tr('Модель скрыта текущим каталогом'))
        if 'inputModalities' in model and 'text' not in model['inputModalities']:notes.append(tr('Текстовый ввод не поддерживается'))
        rule=policies.get(identity)
        if rule:
            notes.append(tr('Предел рассуждения: {effort}',effort=enum_label(rule['maxEffort'])))
            if not rule['automaticEnabled']:notes.append(tr('Автовыбор отключён владельцем'))
        if not efforts:notes.append(tr('Нет разрешённых уровней рассуждения для текущего режима'))
        available=counts[identity]==1 and not model.get('hidden') and ('inputModalities' not in model or 'text' in model['inputModalities']) and bool(efforts)
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
    control=turn_control_state(job)
    if control:result+='\n'+control['title']+'\n'+control['detail']
    elif job.get('pauseRequested') and job['status']!='paused':result+='\n'+tr('Пауза запрошена; отправленный ход может продолжаться.')
    return result
