import time
import pytest
from test_limits import snapshot, window


def limits(five=20, weekly=30, **kwargs):
    return {**snapshot(window(five,300,time.time()+3600),window(weekly,10080,time.time()+86400)),
            'ordinaryUsageAllowed':True, **kwargs}


@pytest.mark.parametrize('mode',['never','confirm','always'])
@pytest.mark.parametrize('five,weekly',[(90,10),(10,90),(100,100)])
def test_both_windows_stop_at_reserve_in_every_mode(mode,five,weekly):
    from mission_control.credit_policy import CreditPolicy, check_credit_limits
    policy=CreditPolicy(mode=mode,paidAcknowledged=mode=='always')
    result=check_credit_limits(limits(five,weekly),'model',policy=policy,observed_at=time.time())
    assert not result['allowed']
    assert result['paidContinuationSupported'] is False


@pytest.mark.parametrize('value',[0,9,9.99,101,True,None,float('nan')])
def test_reserve_cannot_be_less_than_ten(value):
    from mission_control.credit_policy import CreditPolicy
    with pytest.raises(ValueError):CreditPolicy(fiveHourReserve=value)
    with pytest.raises(ValueError):CreditPolicy(weeklyReserve=value)


def test_always_requires_explicit_acknowledgement():
    from mission_control.credit_policy import CreditPolicy
    with pytest.raises(ValueError):CreditPolicy(mode='always')


def test_confirm_is_not_approval_and_credits_do_not_override_service_permission():
    from mission_control.credit_policy import CreditPolicy, check_credit_limits
    data=limits(100,30);data['rateLimitsByLimitId']['codex']['credits']={'hasCredits':True,'unlimited':True,'balance':'999'}
    result=check_credit_limits(data,'model',policy=CreditPolicy(mode='confirm'),observed_at=time.time())
    assert not result['allowed']
    assert result['confirmationRequired'] is True
    data['ordinaryUsageAllowed']=False
    assert not check_credit_limits(data,'model',policy=CreditPolicy(mode='always',paidAcknowledged=True),observed_at=time.time())['allowed']


@pytest.mark.parametrize('data',[None,{},snapshot(window(10)),limits(10,30,ordinaryUsageAllowed=None)])
def test_unknown_subscription_data_never_allows_new_request(data):
    from mission_control.credit_policy import check_credit_limits
    assert not check_credit_limits(data,'model',observed_at=time.time())['allowed']


def test_good_fresh_data_allowed_but_stale_snapshot_blocked():
    from mission_control.credit_policy import check_credit_limits
    data=limits()
    assert check_credit_limits(data,'model',observed_at=time.time())['allowed']
    assert not check_credit_limits(data,'model',observed_at=time.time()-61)['allowed']


def test_credits_are_sanitized_without_account_or_reset_credit_leakage():
    from mission_control.limits import sanitize_limits, inspect_limits
    raw=limits();raw['accountId']='PRIVATE';raw['rateLimitResetCredits']={'availableCount':5,'credits':[{'id':'SECRET'}]}
    raw['rateLimitsByLimitId']['codex']['credits']={'hasCredits':True,'unlimited':False,'balance':'3.50','link':'PRIVATE'}
    clean=sanitize_limits(raw)
    assert clean['rateLimitsByLimitId']['codex']['credits']=={'hasCredits':True,'unlimited':False,'balance':'3.50'}
    assert 'PRIVATE' not in str(clean) and 'SECRET' not in str(clean)
    assert inspect_limits(clean)['credits'][0]['balance']=='3.50'


def test_separate_custom_reserves():
    from mission_control.credit_policy import CreditPolicy, check_credit_limits
    policy=CreditPolicy(fiveHourReserve=25,weeklyReserve=40)
    for data in (limits(75,10),limits(10,60)):
        assert not check_credit_limits(data,'model',policy=policy,observed_at=time.time())['allowed']
    assert check_credit_limits(limits(74,59),'model',policy=policy,observed_at=time.time())['allowed']


@pytest.mark.parametrize('bucket',[None,{}, {'primary':None,'secondary':None},
    {'primary':'malformed','secondary':None}, {'primary':window(10,300)},
    {'primary':window(10,300),'secondary':window(10,10080),'spendControlReached':'unknown'}])
def test_unknown_model_bucket_cannot_hide_behind_healthy_global_quota(bucket):
    from mission_control.credit_policy import check_credit_limits
    data=limits();data['rateLimitsByLimitId']['model']=bucket
    assert not check_credit_limits(data,'model',observed_at=time.time())['allowed']


def test_unknown_limits_never_cross_actual_protocol_wire():
    import asyncio
    from test_integration_protocol import client
    from mission_control.adapter import CodexAdapter
    from mission_control.credit_policy import CreditBlocked
    async def check():
        async with client('unknown_limits') as rpc:
            with pytest.raises(CreditBlocked):
                await CodexAdapter(rpc).run_turn('thread-1','x','first','low')
            assert (await rpc.request('test/counters'))['turn']==0
    asyncio.run(check())


def test_final_guard_reads_credit_policy_after_waiting_for_writer(tmp_path):
    import asyncio
    from test_integration_protocol import client
    from mission_control.adapter import CodexAdapter
    from mission_control.credit_policy import CreditBlocked
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue
    facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'))
    facade.save_preferences({'creditPolicy':{'mode':'never','fiveHourReserve':10,'weeklyReserve':10}})
    async def check():
        with facade.queue.storage():
            async with client('wire') as rpc:
                original=rpc._send
                async def send(message, **kwargs):
                    if message.get('method')=='turn/start':
                        facade.save_preferences({'creditPolicy':{'mode':'never','fiveHourReserve':95,'weeklyReserve':10}})
                    await original(message,**kwargs)
                rpc._send=send
                with pytest.raises(CreditBlocked):
                    await CodexAdapter(rpc).run_turn('thread-1','x','first','low')
                assert (await rpc.request('test/counters'))['turn']==0
    asyncio.run(check())


def test_newer_notification_revokes_preflight_before_wire_write():
    import asyncio
    from test_integration_protocol import client
    from mission_control.adapter import CodexAdapter
    from mission_control.credit_policy import CreditBlocked
    from mission_control.limits import merge_limit_update
    async def check():
        async with client('wire') as rpc:
            original=rpc._send
            async def send(message,**kwargs):
                if message.get('method')=='turn/start':
                    rpc.rate_limit_snapshot=merge_limit_update(rpc.rate_limit_snapshot,{'ordinaryUsageAllowed':False})
                await original(message,**kwargs)
            rpc._send=send
            with pytest.raises(CreditBlocked):
                await CodexAdapter(rpc).run_turn('thread-1','x','first','low')
            assert (await rpc.request('test/counters'))['turn']==0
    asyncio.run(check())


@pytest.mark.parametrize('update',[{'rateLimitsByLimitId':{'codex':None}},
    {'rateLimits':None},{'rateLimitsByLimitId':None}])
def test_explicit_unknown_notification_invalidates_previous_healthy_snapshot(update):
    from mission_control.limits import merge_limit_update
    from mission_control.credit_policy import check_credit_limits
    previous=limits()
    merged=merge_limit_update(previous,update)
    assert not check_credit_limits(merged,'model',observed_at=time.time())['allowed']


def test_durable_credit_pause_and_explicit_resume_after_recovery(tmp_path):
    import asyncio
    from test_managed import Service, start, engine
    from mission_control.credit_policy import check_credit_limits
    class CreditService(Service):
        async def credit_gate(self, model, *, limits=None):
            return check_credit_limits(limits,model,observed_at=time.time())
    service=CreditService();service.limits=limits(90,10)
    saved=start(tmp_path,service,max_wait=0)
    assert saved['stage']=='waiting_credit' and saved['attempts']==[]
    assert service.submissions==[] and service.connected==0
    service.limits=limits();service.now=saved['nextCheckAt']
    resumed=asyncio.run(engine(tmp_path,service).resume(max_wait=0))
    assert resumed['stage']=='completed' and len(service.submissions)==1


def test_final_credit_rejection_preserves_no_send_receipt_and_attempt_budget(tmp_path):
    import asyncio
    from test_managed import Service,start,engine
    from mission_control.credit_policy import CreditBlocked,check_credit_limits
    class RejectService(Service):
        async def run_turn(self,*args,**kwargs):
            raise CreditBlocked(check_credit_limits(limits(90,10),'model',observed_at=time.time()))
    service=RejectService()
    saved=start(tmp_path,service,max_wait=0)
    assert saved['stage']=='waiting_credit' and saved['attempts']==[]
    assert saved['preSendRejection']['status']=='not_started'
    assert 'threadId' not in saved
    service.run_turn=Service.run_turn.__get__(service)
    service.now=saved['nextCheckAt']
    assert asyncio.run(engine(tmp_path,service).resume(max_wait=0))['stage']=='completed'


def test_unknown_credit_data_does_not_prevent_reconciliation(tmp_path):
    import asyncio
    from test_managed import Service,start,engine
    from mission_control.credit_policy import check_credit_limits
    class CreditService(Service):
        async def credit_gate(self,model,*,limits=None):
            return check_credit_limits(limits,model,observed_at=time.time())
    service=CreditService();service.limits=limits();service.drop_ack=True
    saved=start(tmp_path,service,max_wait=0)
    service.limits={};service.now=saved['nextCheckAt']
    assert asyncio.run(engine(tmp_path,service).resume(max_wait=0))['stage']=='completed'
    assert len(service.submissions)==1


def test_credit_preferences_and_portable_roundtrip(tmp_path):
    from dataclasses import asdict
    from mission_control.credit_policy import CreditPolicy
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue
    from mission_control.transfer import export_archive,import_archive
    from mission_control.state import StateError
    facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'))
    policy=asdict(CreditPolicy(mode='confirm',fiveHourReserve=20,weeklyReserve=35))
    facade.save_preferences({'creditPolicy':policy})
    assert facade.preferences()['creditPolicy']==policy
    with pytest.raises(StateError):facade.save_preferences({'creditPolicy':{'mode':'always'}})
    archive=tmp_path/'prefs.cmcp'
    export_archive(archive,'abcdefghijkl',preferences=facade.preferences(),projects=[],history=[])
    assert import_archive(archive,'abcdefghijkl')['preferences']['creditPolicy']==policy


def test_credit_editor_requires_visible_informed_choice_and_retains_unsaved_edits():
    from PySide6.QtWidgets import QApplication
    from mission_control.desktop.credit_policy import CreditPolicyEditor
    app=QApplication.instance() or QApplication([])
    editor=CreditPolicyEditor();editor.update_data({})
    assert editor.value()['fiveHourReserve']==10 and not editor.ack.isEnabled()
    editor.mode.setCurrentIndex(editor.mode.findData('always'))
    assert editor.ack.isEnabled() and not editor.value()['paidAcknowledged']
    editor.ack.setChecked(True);editor.five.setValue(25);editor.update_data({})
    assert editor.value()['paidAcknowledged'] and editor.value()['fiveHourReserve']==25
