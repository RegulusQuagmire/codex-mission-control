import asyncio
import pytest


class Adapter:
    def __init__(self):
        self.calls=[];self.active=True;self.allowed=True
        self.rpc=self
    async def read_thread(self,identity):
        return {'id':identity,'turns':[{'id':'t','status':'inProgress' if self.active else 'completed'}]}
    async def credit_gate(self,model):return {'allowed':self.allowed,'reason':'reserve_reached'}
    async def request(self,method,params,**kwargs):
        self.calls.append((method,params));return {'turnId':'t'} if method=='turn/steer' else {}


def test_pause_steers_once_then_interrupts_once_with_durable_intents():
    from mission_control.pause import TurnControl
    async def check():
        adapter=Adapter();receipts=[];now=[0]
        control=TurnControl(adapter,'thread','t','m',stop_requested=lambda:True,
                            receipt=receipts.append,clock=lambda:now[0],grace=5)
        await control.tick();await control.tick()
        assert [m for m,p in adapter.calls]==['turn/steer']
        now[0]=6;await control.tick();await control.tick()
        assert [m for m,p in adapter.calls]==['turn/steer','turn/interrupt']
        assert adapter.calls[0][1]['expectedTurnId']=='t'
        assert adapter.calls[1][1]=={'threadId':'thread','turnId':'t'}
        assert [v['phase'] for v in receipts]==['steer_requested','steer_acknowledged','interrupt_requested','interrupt_acknowledged']
        assert receipts[-1]['terminalConfirmed'] is False
    asyncio.run(check())


@pytest.mark.parametrize('failure,expected',[
    ('rpc',{'kind':'rpc_rejected','code':-32603}),
    ('unsupported',{'kind':'rpc_rejected','code':-32601}),
    ('timeout',{'kind':'timeout_outcome_unknown'})])
def test_control_failure_retains_safe_diagnostic_without_retry(failure,expected):
    from mission_control.pause import TurnControl
    from mission_control.rpc import RpcError
    async def check():
        adapter=Adapter();receipts=[];original=adapter.request
        async def request(method,params,**kwargs):
            if method=='turn/interrupt':
                adapter.calls.append((method,params))
                if failure=='timeout':raise TimeoutError()
                raise RpcError(method,-32601 if failure=='unsupported' else -32603)
            return await original(method,params,**kwargs)
        adapter.request=request
        control=TurnControl(adapter,'thread','t','m',stop_requested=lambda:True,
                            receipt=receipts.append,grace=0)
        await control.tick();await control.tick()
        assert receipts[-1]['phase']=='interrupt_unavailable_or_unknown'
        assert receipts[-1]['failure']==expected
        assert receipts[-1]['terminalConfirmed'] is False
        assert [m for m,p in adapter.calls]==['turn/steer','turn/interrupt']
    asyncio.run(check())


def test_control_connection_loss_is_persisted_then_propagates_without_retry():
    from mission_control.pause import TurnControl
    from mission_control.rpc import ConnectionLost
    async def check():
        adapter=Adapter();receipts=[];original=adapter.request
        async def request(method,params,**kwargs):
            if method=='turn/interrupt':
                adapter.calls.append((method,params));raise ConnectionLost('PRIVATE_DETAIL')
            return await original(method,params,**kwargs)
        adapter.request=request
        control=TurnControl(adapter,'thread','t','m',stop_requested=lambda:True,
                            receipt=receipts.append,grace=0)
        with pytest.raises(ConnectionLost):await control.tick()
        await control.tick()
        assert receipts[-1]['failure']=={'kind':'connection_lost_outcome_unknown'}
        assert 'PRIVATE_DETAIL' not in str(receipts)
        assert receipts[-1]['terminalConfirmed'] is False
        assert [m for m,p in adapter.calls]==['turn/steer','turn/interrupt']
    asyncio.run(check())


def test_quota_restriction_starts_pause_but_healthy_quota_does_not():
    from mission_control.pause import TurnControl
    async def check():
        adapter=Adapter();control=TurnControl(adapter,'thread','t','m',stop_requested=lambda:False)
        await control.tick();assert not adapter.calls
        adapter.allowed=False;control.next_check=0
        await control.tick();assert adapter.calls[0][0]=='turn/steer'
        assert control.reason=='reserve_reached'
    asyncio.run(check())


def test_mismatched_turn_never_steers_or_interrupts():
    from mission_control.pause import TurnControl
    async def check():
        adapter=Adapter();control=TurnControl(adapter,'thread','different','m',stop_requested=lambda:True)
        await control.tick();assert not adapter.calls
    asyncio.run(check())


def test_terminal_turn_never_receives_control_request():
    from mission_control.pause import TurnControl
    async def check():
        adapter=Adapter();adapter.active=False
        control=TurnControl(adapter,'thread','t','m',stop_requested=lambda:True)
        await control.tick();assert not adapter.calls
    asyncio.run(check())


def test_actual_adapter_protocol_pause_has_matching_terminal_and_checkpoint():
    from test_integration_protocol import client
    from mission_control.adapter import CodexAdapter,TurnPaused
    async def check():
        async with client('pause_active') as rpc:
            adapter=CodexAdapter(rpc);receipts=[];checkpoints=[]
            adapter.configure_pause(stop_requested=lambda:True,on_receipt=receipts.append,
                                    on_checkpoint=checkpoints.append,grace=.01)
            with pytest.raises(TurnPaused) as error:
                await adapter.run_turn('thread-1','x','first','low',timeout=5)
            assert error.value.receipt['terminalConfirmed'] is True
            assert receipts[-1]['phase']=='terminal_interrupted'
            assert checkpoints[-1].startswith('Checkpoint:')
            assert (await rpc.request('test/counters'))=={'resume':0,'turn':1,'interrupt':1,'steer':1}
    asyncio.run(check())


def test_active_acknowledged_turn_does_not_require_rollout_history_hydration():
    """Real QA: active full-history thread/read failed before any control RPC."""
    from test_integration_protocol import client
    from mission_control.adapter import CodexAdapter,TurnPaused
    from mission_control.rpc import RpcError
    async def check():
        async with client('pause_active') as rpc:
            adapter=CodexAdapter(rpc);original=adapter.read_thread
            async def persisted_history_only(thread_id):
                if thread_id not in adapter._fresh_threads:
                    raise RpcError('thread/read',-32603)
                return await original(thread_id)
            adapter.read_thread=persisted_history_only
            adapter._fresh_threads.add('thread-1')
            adapter.configure_pause(stop_requested=lambda:True,grace=0)
            with pytest.raises(TurnPaused):
                await adapter.run_turn('thread-1','text only','first','low',timeout=5)
            counts=await rpc.request('test/counters')
            assert counts['turn']==1 and counts['steer']==1 and counts['interrupt']==1
    asyncio.run(check())


def test_durable_pause_requires_review_then_continues_same_mission_once(tmp_path):
    from test_managed import Service,start,engine
    from mission_control.adapter import TurnPaused
    from mission_control.state import load_state,save_state,StateError
    class PausingService(Service):
        def configure_pause(self,**options):self.options=options
        async def run_turn(self,thread_id,text,model,effort,*,timeout,on_started):
            if self.turns:return await super().run_turn(thread_id,text,model,effort,timeout=timeout,on_started=on_started)
            self.submissions.append((thread_id,text,model,effort));on_started('paused')
            self.turns.append({'id':'paused','status':'interrupted','itemsView':'full','items':[]})
            self.options['on_checkpoint']('Completed: planning only. Next: answer 2.')
            receipt={'threadId':thread_id,'turnId':'paused','reason':'user_pause',
                     'phase':'terminal_interrupted','terminalConfirmed':True}
            self.options['on_receipt'](receipt);raise TurnPaused(receipt)
    service=PausingService();saved=start(tmp_path,service,max_wait=0)
    assert saved['stage']=='waiting_resume' and saved['attempts'][0]['phase']=='paused_turn'
    unchanged=asyncio.run(engine(tmp_path,service).resume(max_wait=0))
    assert unchanged['stage']=='waiting_resume' and len(service.submissions)==1
    with pytest.raises(StateError,match='does not match'):
        asyncio.run(engine(tmp_path,service).resume(max_wait=0,reviewed_turn_id='different'))
    done=asyncio.run(engine(tmp_path,service).resume(max_wait=0,reviewed_turn_id='paused'))
    assert done['stage']=='completed' and len(service.submissions)==2
    assert service.submissions[1][0]==service.submissions[0][0]
    assert 'Completed: planning only.' in service.submissions[1][1]
    assert asyncio.run(engine(tmp_path,service).resume(max_wait=0))['stage']=='completed'
    assert len(service.submissions)==2


@pytest.mark.parametrize('status',['interrupted','completed'])
def test_lost_terminal_event_reconciles_into_review_without_replay(tmp_path,status):
    from test_managed import Service,start,engine
    from mission_control.state import load_state,save_state
    service=Service();service.drop_ack=True
    saved=start(tmp_path,service,max_wait=0)
    attempt=saved['attempts'][-1]
    attempt['turnId']='1'
    attempt['checkpoint']='Durably saved partial text'
    attempt['pauseReceipt']={'threadId':'thread','turnId':'1','phase':'steer_acknowledged',
                             'reason':'user_pause','terminalConfirmed':False}
    service.turns[0]['status']=status;service.turns[0]['items']=[];save_state(tmp_path/'job.json',saved)
    service.now=saved['nextCheckAt']
    paused=asyncio.run(engine(tmp_path,service).resume(max_wait=0))
    assert paused['stage']=='waiting_resume'
    assert paused['attempts'][-1]['pauseReceipt']['terminalConfirmed'] is True
    assert paused['attempts'][-1]['checkpoint']=='Durably saved partial text'
    assert len(service.submissions)==1


def test_queue_continuation_approval_is_bound_to_exact_paused_turn_and_lease(tmp_path):
    from test_queue import text_job
    from mission_control.queue import MissionQueue
    from mission_control.state import load_state,save_state,state_lock,StateError
    queue=MissionQueue(tmp_path/'q.json');queue.add(text_job('job',project=str(tmp_path)))
    data=queue.read();job=data['missions']['job'];path=queue.run_path(job)
    save_state(path,{'attempts':[{'phase':'paused_turn','turnId':'paused'}]})
    job.update(runPath=str(path),status='waiting_resume',dispatchStarted=True)
    data['active']='job';save_state(queue.path,data)
    for values in ({},{'acknowledge_uncertain':True},{'acknowledge_uncertain':True,'expected_turn_id':'different'}):
        with pytest.raises(StateError):queue.control('resume','job',**values)
    with state_lock(path):
        with pytest.raises(StateError):queue.control('resume','job',acknowledge_uncertain=True,expected_turn_id='paused')
    queue.control('resume','job',acknowledge_uncertain=True,expected_turn_id='paused')
    assert load_state(path)['attempts'][-1]['continuationApproved']=='paused'




def test_cooperative_completion_preserves_commentary_only_checkpoint(tmp_path):
    from test_managed import Service,start
    class SoftService(Service):
        def configure_pause(self,**options):self.options=options
        async def run_turn(self,thread_id,text,model,effort,*,timeout,on_started):
            on_started('soft');self.options['on_checkpoint']('Durable commentary checkpoint')
            return {'turnId':'soft','status':'completed','text':'','pauseReceipt':{
                'threadId':thread_id,'turnId':'soft','terminalConfirmed':True,
                'reason':'user_pause','phase':'terminal_completed'}}
    saved=start(tmp_path,SoftService(),max_wait=0)
    assert saved['stage']=='waiting_resume'
    assert saved['attempts'][-1]['checkpoint']=='Durable commentary checkpoint'


def test_terminal_receipt_does_not_erase_last_control_failure(tmp_path):
    from test_managed import Service,start
    class SoftService(Service):
        def configure_pause(self,**options):self.options=options
        async def run_turn(self,thread_id,text,model,effort,*,timeout,on_started):
            on_started('soft')
            self.options['on_receipt']({'threadId':thread_id,'turnId':'soft',
                'phase':'interrupt_unavailable_or_unknown','terminalConfirmed':False,
                'failure':{'kind':'rpc_rejected','code':-32603}})
            terminal={'threadId':thread_id,'turnId':'soft','terminalConfirmed':True,
                      'reason':'user_pause','phase':'terminal_completed'}
            self.options['on_receipt'](terminal)
            return {'turnId':'soft','status':'completed','text':'checkpoint',
                    'pauseReceipt':terminal}
    saved=start(tmp_path,SoftService(),max_wait=0)
    attempt=saved['attempts'][-1]
    assert saved['stage']=='waiting_resume'
    assert attempt['pauseReceipt']['phase']=='terminal_completed'
    assert attempt['lastControlFailure']['failure']=={'kind':'rpc_rejected','code':-32603}
    assert attempt['lastControlFailure']['turnId']=='soft'


def test_unsupported_steer_falls_back_once_without_claiming_termination():
    from mission_control.pause import TurnControl
    from mission_control.rpc import RpcError
    async def check():
        class Unsupported(Adapter):
            async def request(self,method,params,**kwargs):
                if method=='turn/steer':
                    self.calls.append((method,params));raise RpcError(method,-32601)
                return await super().request(method,params,**kwargs)
        adapter=Unsupported();receipts=[]
        control=TurnControl(adapter,'thread','t','m',stop_requested=lambda:True,receipt=receipts.append)
        await control.tick();await control.tick()
        assert [m for m,p in adapter.calls]==['turn/steer','turn/interrupt']
        assert not any(r['terminalConfirmed'] for r in receipts)
    asyncio.run(check())


def test_interrupt_ack_without_terminal_event_stays_uncertain_and_never_repeats():
    from test_integration_protocol import client
    from mission_control.adapter import CodexAdapter
    async def check():
        async with client('pause_no_terminal') as rpc:
            adapter=CodexAdapter(rpc);receipts=[]
            adapter.configure_pause(stop_requested=lambda:True,on_receipt=receipts.append,grace=0)
            with pytest.raises(TimeoutError):
                await adapter.run_turn('thread-1','x','first','low',timeout=2)
            counters=await rpc.request('test/counters')
            assert counters['interrupt']==1 and counters['steer']==1 and counters['turn']==1
            assert not any(r['terminalConfirmed'] for r in receipts)
    asyncio.run(check())


def test_credit_reset_wait_closes_connection_then_rechecks_before_continuing(tmp_path):
    import time
    from test_managed import Service,start
    from test_credit_policy import limits
    from mission_control.credit_policy import check_credit_limits
    class CreditService(Service):
        async def credit_gate(self,model,*,limits=None):
            return check_credit_limits(limits,model,observed_at=time.time())
    service=CreditService();service.now=time.time();service.limits=limits(90,10)
    service.limits['rateLimitsByLimitId']['codex']['primary']['resetsAt']=service.now+1
    service.on_sleep=lambda:setattr(service,'limits',limits())
    saved=start(tmp_path,service,max_wait=20)
    assert saved['stage']=='completed' and len(service.submissions)==1
    assert len(service.sleeps)==1 and 5<service.sleeps[0]<=6
    assert service.connected==0
