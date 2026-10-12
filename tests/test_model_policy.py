import asyncio
import sys
from pathlib import Path

import pytest

from mission_control.routing import SmartRouter, Task, Mode, RoutingBlocked, manual_decision
from test_routing import catalog


PROFILE = {'gpt-6-astra': {'maxEffort': 'low', 'automaticEnabled': True},
           'gpt-6.1-sol': {'maxEffort': 'medium', 'automaticEnabled': True},
           'gpt-6-luna': {'maxEffort': 'high', 'automaticEnabled': True}}


@pytest.mark.parametrize('mode', list(Mode))
def test_all_modes_and_escalations_obey_individual_ceiling(mode):
    from mission_control.model_policy import policy_context, validate_configuration
    with policy_context(lambda: PROFILE):
        router = SmartRouter()
        decision = router.choose(Task('Architecture', operation='architecture'), catalog(), mode)
        visited = set()
        while decision:
            validate_configuration(catalog(), decision.model, decision.effort, automatic=True)
            visited.add((decision.model, decision.effort))
            assert len(visited) <= 15
            decision = router.escalate(decision, catalog(), visited)


def test_manual_ceiling_and_automatic_switch_are_distinct():
    from mission_control.model_policy import policy_context
    rules = {'gpt-6-luna': {'maxEffort': 'low', 'automaticEnabled': False}}
    task = Task('text', operation='text')
    with policy_context(lambda: rules):
        assert SmartRouter().choose(task, catalog(), Mode.ECONOMY).model != 'gpt-6-luna'
        assert manual_decision(task, catalog(), {'model':'gpt-6-luna','effort':'low'}, 'economy')
        with pytest.raises(RoutingBlocked):
            manual_decision(task, catalog(), {'model':'gpt-6-luna','effort':'medium'}, 'economy')


def test_no_automatic_configuration_stops():
    from mission_control.model_policy import policy_context
    rules = {m['model']: {'maxEffort': 'low', 'automaticEnabled': False} for m in catalog()}
    with policy_context(lambda: rules), pytest.raises(RoutingBlocked):
        SmartRouter().choose(Task('text'), catalog())


@pytest.mark.parametrize('rules', [None, [], {'x':{}}, {'x':{'maxEffort':'unknown','automaticEnabled':True}},
    {'x':{'maxEffort':'low','automaticEnabled':1}}, {'':{'maxEffort':'low','automaticEnabled':True}}])
def test_malformed_policy_fails_closed(rules):
    from mission_control.model_policy import validate_policy
    with pytest.raises(ValueError): validate_policy(rules)


def test_adapter_reads_current_policy_under_write_lock():
    from mission_control.adapter import CodexAdapter
    from mission_control.model_policy import policy_context
    from mission_control.rpc import RpcClient
    async def check():
        rules = {}
        command = [sys.executable, str(Path(__file__).with_name('fake_server.py')), 'wire']
        async with RpcClient(command) as rpc:
            adapter = CodexAdapter(rpc)
            await rpc._write_lock.acquire()
            with policy_context(lambda: rules):
                task = asyncio.create_task(adapter.run_turn('thread-1', 'x', 'first', 'low'))
                await asyncio.sleep(.05)
                rules['first'] = {'maxEffort':'none','automaticEnabled':True}
                rpc._write_lock.release()
                with pytest.raises(RoutingBlocked): await task
            assert (await rpc.request('test/counters'))['turn'] == 0
    asyncio.run(check())


def test_settings_editor_retains_missing_ids_and_saved_caps():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from mission_control.desktop.model_policy import ModelPolicyEditor
    editor = ModelPolicyEditor()
    editor.update_data(catalog(), PROFILE)
    assert editor.value() == PROFILE
    reduced = [m for m in catalog() if m['model'] != 'gpt-6-astra']
    editor.update_data(reduced, PROFILE)
    assert editor.value() == PROFILE
    assert 'gpt-6-astra' in editor.controls
    assert 'недоступна' in editor.controls['gpt-6-astra'][2].text().lower()


def test_policy_roundtrip_and_invalid_preferences(tmp_path):
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue
    from mission_control.state import StateError
    from mission_control.transfer import _summary
    facade = DesktopService(MissionQueue(tmp_path/'q.sqlite3'))
    facade.save_preferences({'modelPolicies':PROFILE})
    assert DesktopService(MissionQueue(facade.queue.path)).preferences()['modelPolicies'] == PROFILE
    assert _summary(facade.preferences(), [], [])['preferences']['modelPolicies'] == PROFILE
    with pytest.raises(StateError): facade.save_preferences({'modelPolicies':{'x':{}}})


def test_sqlite_cli_queue_enforces_saved_desktop_policy(tmp_path, monkeypatch):
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue, QueueWorker
    from mission_control.safety import approve
    from test_queue import text_job
    from test_managed import Service
    monkeypatch.setattr('mission_control.queue.worker_lease_path', lambda:tmp_path/'worker')
    project=tmp_path/'project';project.mkdir()
    facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'))
    facade.configure_roots([str(project)])
    facade.save_preferences({'modelPolicies':PROFILE})
    job=text_job('manual',project=str(project));job['manual']={'model':'gpt-6-astra','effort':'high'}
    facade.add(job);approve(facade.queue,'manual')
    service=Service()
    result=asyncio.run(QueueWorker(facade.queue,lambda cwd:service.factory).run(max_wait=0))
    assert not service.submissions
    assert result['missions']['manual']['status']=='waiting_model'


def test_saved_decision_rechecked_after_policy_tightening(tmp_path):
    from mission_control.model_policy import policy_context
    from test_managed import Service, start, engine
    from test_limits import snapshot, window
    service=Service();service.limits=snapshot(window(100,reset=None))
    rules={}
    with policy_context(lambda:rules):
        saved=start(tmp_path,service,max_wait=0)
        model=saved['decision']['model']
        rules[model]={'maxEffort':'none','automaticEnabled':True}
        service.limits=snapshot(window(0))
        service.now=saved['nextCheckAt']
        resumed=asyncio.run(engine(tmp_path,service).resume(max_wait=0))
        assert resumed['stage']=='needs_attention'
        assert not service.submissions


def test_tightening_after_catalog_read_before_wire_write():
    from mission_control.adapter import CodexAdapter
    from mission_control.model_policy import policy_context
    from mission_control.rpc import RpcClient
    async def check():
        rules={};reached=asyncio.Event();release=asyncio.Event()
        async with RpcClient([sys.executable,str(Path(__file__).with_name('fake_server.py')),'wire']) as rpc:
            original=rpc._send
            async def send(message, **kwargs):
                if message.get('method')=='turn/start':
                    reached.set();await release.wait()
                return await original(message, **kwargs)
            rpc._send=send
            with policy_context(lambda:rules):
                task=asyncio.create_task(CodexAdapter(rpc).run_turn('thread-1','x','first','low'))
                await asyncio.wait_for(reached.wait(),3)
                rules['first']={'maxEffort':'none','automaticEnabled':True}
                release.set()
                with pytest.raises(RoutingBlocked):await task
            assert (await rpc.request('test/counters'))['turn']==0
            assert rpc.pending=={}
    asyncio.run(check())


@pytest.mark.parametrize('effort', ['high', 'unrecognized'])
def test_stale_or_unknown_catalog_effort_never_crosses_wire(effort):
    from mission_control.adapter import CodexAdapter
    from mission_control.rpc import RpcClient
    async def check():
        async with RpcClient([sys.executable,str(Path(__file__).with_name('fake_server.py')),'wire']) as rpc:
            with pytest.raises(RoutingBlocked):
                await CodexAdapter(rpc).run_turn('thread-1','x','first',effort)
            assert (await rpc.request('test/counters'))['turn']==0
    asyncio.run(check())


def test_uncertain_attempt_reconciles_despite_new_policy(tmp_path):
    from mission_control.model_policy import policy_context
    from test_managed import Service, start, engine
    service=Service();service.drop_ack=True
    rules={}
    with policy_context(lambda:rules):
        saved=start(tmp_path,service,max_wait=0)
        rules[saved['decision']['model']]={'maxEffort':'none','automaticEnabled':False}
        service.now=saved['nextCheckAt']
        resumed=asyncio.run(engine(tmp_path,service).resume(max_wait=0))
        assert resumed['stage']=='completed'
        assert len(service.submissions)==1


def test_final_guard_rejection_is_durable_known_not_started(tmp_path):
    from contextlib import asynccontextmanager
    from mission_control.adapter import CodexAdapter
    from mission_control.managed import ManagedRunner
    from mission_control.model_policy import policy_context
    from mission_control.rpc import RpcClient
    from test_limits import snapshot, window
    rules={};counters=[]
    @asynccontextmanager
    async def factory():
        async with RpcClient([sys.executable,str(Path(__file__).with_name('fake_server.py')),'wire']) as rpc:
            adapter=CodexAdapter(rpc)
            from test_credit_policy import limits as credit_limits
            async def limits():return credit_limits()
            adapter.rate_limits=limits
            original=rpc._send
            async def send(message, **kwargs):
                if message.get('method')=='turn/start':
                    rules['first']={'maxEffort':'none','automaticEnabled':True}
                await original(message,**kwargs)
            rpc._send=send
            yield adapter
            counters.append(await rpc.request('test/counters'))
    runner=ManagedRunner(factory,tmp_path/'run.json',cwd=tmp_path)
    with policy_context(lambda:rules):
        result=asyncio.run(runner.run(Task('x',operation='text'),expected='2',max_wait=0))
        assert result['stage']=='needs_attention'
        assert result['attempts'][-1]['phase']=='failed'
        assert result['attempts'][-1]['failure']['status']=='not_started'
        assert not result.get('threadId')
        resumed=asyncio.run(runner.resume(max_wait=0))
        assert resumed['stage']=='needs_attention'
    assert counters==[{'resume':0,'turn':0,'interrupt':0}]


def test_preferences_read_and_merge_are_inside_policy_lock(tmp_path, monkeypatch):
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue
    from mission_control.state import state_lock, StateError
    facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'))
    facade.save_preferences({'modelPolicies':PROFILE})
    original=facade.preferences
    def checked_preferences():
        # Windows leases also arbitrate separate handles in one process.
        import os
        if os.name=='nt':
            with pytest.raises(StateError):
                with state_lock(facade.queue.path):pass
        return original()
    monkeypatch.setattr(facade,'preferences',checked_preferences)
    facade.save_preferences({'theme':'light'})
    assert original()['modelPolicies']==PROFILE


def test_final_policy_read_holds_queue_lease_until_write(tmp_path):
    import os
    if os.name!='nt':pytest.skip('Windows byte-range lease contention probe')
    from mission_control.adapter import CodexAdapter
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue
    from mission_control.rpc import RpcClient
    from mission_control.state import state_lock, StateError
    facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'));facade.save_preferences({'modelPolicies':{}})
    async def check():
        with facade.queue.storage():
            async with RpcClient([sys.executable,str(Path(__file__).with_name('fake_server.py')),'wire']) as rpc:
                original=rpc.process.stdin.write
                def write(data):
                    import json
                    if json.loads(data).get('method')=='turn/start':
                        with pytest.raises(StateError):
                            with state_lock(facade.queue.path):pass
                    original(data)
                rpc.process.stdin.write=write
                await CodexAdapter(rpc).run_turn('thread-1','x','first','low')
                assert (await rpc.request('test/counters'))['turn']==1
        with state_lock(facade.queue.path):pass  # Released after the synchronous write.
    asyncio.run(check())


def test_settings_save_stays_visible_at_small_window():
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QPushButton
    from test_desktop_gui import Bridge, empty
    from mission_control.desktop.window import MainWindow
    app=QApplication.instance() or QApplication([])
    window=MainWindow(Bridge(),system_integration=False)
    data=empty();data['models']=catalog();data['preferences']['modelPolicies']=PROFILE
    window.update_snapshot(data);window.resize(900,650);window.navigation.setCurrentRow(6)
    window.show();app.processEvents()
    save=next(b for b in window.settings.findChildren(QPushButton) if b.text()=='Сохранить')
    assert save.mapTo(window,QPoint(0,0)).y()+save.height()<=window.height()
    window.close()
