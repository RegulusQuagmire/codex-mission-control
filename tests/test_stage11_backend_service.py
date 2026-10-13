"""Offline service/SQLite integration of reviewed Stage 11 continuation.

Only the remote Codex adapter is synthetic; queue, journals, approvals and
DesktopService worker dispatch are real. No UI or account is instantiated.
"""
import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from mission_control.desktop.service import DesktopService
from mission_control.queue import MissionQueue
from mission_control.safety import approve
from mission_control.state import StateError, load_state, save_state, state_lock
from test_managed import Service
from test_queue import text_job


class PausingService(Service):
    def configure_pause(self, **options):
        self.pause_options = options

    async def run_turn(self, thread_id, text, model, effort, *, timeout, on_started):
        if self.turns:
            return await super().run_turn(thread_id, text, model, effort,
                                          timeout=timeout, on_started=on_started)
        from mission_control.adapter import TurnPaused
        self.submissions.append((thread_id, text, model, effort))
        on_started('paused-1')
        self.turns.append({'id': 'paused-1', 'status': 'interrupted',
                           'itemsView': 'full', 'items': []})
        self.pause_options['on_checkpoint']('Completed: planning only. Next: answer 2.')
        receipt = {'threadId': thread_id, 'turnId': 'paused-1',
                   'reason': 'user_pause', 'phase': 'terminal_interrupted',
                   'terminalConfirmed': True}
        self.pause_options['on_receipt'](receipt)
        raise TurnPaused(receipt)


def paused_service(tmp_path, monkeypatch, *, max_attempts=3):
    monkeypatch.setattr('mission_control.queue.worker_lease_path', lambda: tmp_path/'worker')
    project = tmp_path/'project'
    project.mkdir()
    queue = MissionQueue(tmp_path/'queue.sqlite3')
    remote = PausingService()
    facade = DesktopService(queue, factory_for_cwd=lambda cwd: remote.factory)
    facade.configure_roots([str(project)])
    facade.save_preferences({'language': 'en'})
    facade.add(text_job('mission', project=str(project), maxAttempts=max_attempts))
    approve(queue, 'mission')
    initial = asyncio.run(facade.start())
    assert initial['missions']['mission']['status'] == 'waiting_resume'
    assert initial['active'] == 'mission'
    assert len(remote.submissions) == 1
    return facade, remote


def saved_run(facade):
    with facade.queue.storage():
        job = facade.queue.read()['missions']['mission']
        return load_state(Path(job['runPath']))


@pytest.mark.parametrize('values', [
    {}, {'acknowledge_uncertain': True}, {'expected_turn_id': 'paused-1'},
    {'acknowledge_uncertain': True, 'expected_turn_id': 'old-turn'},
])
def test_service_rejects_missing_or_stale_consent_without_starting_worker(tmp_path, monkeypatch, values):
    facade, remote = paused_service(tmp_path, monkeypatch)
    before = deepcopy(saved_run(facade))
    with pytest.raises(StateError):
        asyncio.run(facade.resume_mission('mission', **values))
    assert saved_run(facade) == before
    assert facade.worker_task is None
    assert len(remote.submissions) == 1


def test_service_restart_keeps_checkpoint_and_queue_resume_never_grants_consent(tmp_path, monkeypatch):
    facade, remote = paused_service(tmp_path, monkeypatch)
    facade.control('pause')
    restored = DesktopService(MissionQueue(facade.queue.path),
                              factory_for_cwd=lambda cwd: remote.factory)
    restored.initialize()
    assert restored.preferences()['language'] == 'en'
    snapshot = restored.snapshot()
    live = snapshot['missions'][0]['live']
    assert live['stage'] == 'waiting_resume'
    assert live['attempts'][-1]['checkpoint'] == 'Completed: planning only. Next: answer 2.'
    assert 'continuationApproved' not in live['attempts'][-1]
    resumed = asyncio.run(restored.resume_queue())
    assert not resumed['paused']
    assert resumed['missions']['mission']['status'] == 'waiting_resume'
    assert len(remote.submissions) == 1
    assert 'continuationApproved' not in saved_run(restored)['attempts'][-1]


def test_service_exact_consent_continues_same_thread_once_and_preserves_language(tmp_path, monkeypatch):
    facade, remote = paused_service(tmp_path, monkeypatch)
    result = asyncio.run(facade.resume_mission('mission', acknowledge_uncertain=True,
                                              expected_turn_id='paused-1'))
    assert result['missions']['mission']['status'] == 'completed'
    assert result['active'] is None
    assert len(remote.submissions) == 2
    assert [call[0] for call in remote.submissions] == ['thread', 'thread']
    run = saved_run(facade)
    assert run['attempts'][0]['continuationApproved'] == 'paused-1'
    assert len(run['attempts']) == 2 and run['maxAttempts'] == 3
    assert facade.preferences()['language'] == 'en'
    asyncio.run(facade.start())
    with pytest.raises(StateError):
        asyncio.run(facade.resume_mission('mission', acknowledge_uncertain=True,
                                        expected_turn_id='paused-1'))
    assert len(remote.submissions) == 2


def test_service_review_respects_run_lock_and_does_not_approve_on_contention(tmp_path, monkeypatch):
    facade, remote = paused_service(tmp_path, monkeypatch)
    path = Path(facade.queue.read()['missions']['mission']['runPath'])
    with state_lock(path):
        with pytest.raises(StateError):
            asyncio.run(facade.resume_mission('mission', acknowledge_uncertain=True,
                                            expected_turn_id='paused-1'))
    assert 'continuationApproved' not in saved_run(facade)['attempts'][-1]
    assert len(remote.submissions) == 1


@pytest.mark.parametrize('history', ['missing', 'active'])
def test_service_review_cannot_override_missing_or_nonterminal_history(tmp_path, monkeypatch, history):
    facade, remote = paused_service(tmp_path, monkeypatch)
    if history == 'missing':
        remote.turns.clear()
    else:
        remote.turns[0]['status'] = 'inProgress'
    result = asyncio.run(facade.resume_mission('mission', acknowledge_uncertain=True,
                                              expected_turn_id='paused-1'))
    assert result['missions']['mission']['status'] == 'needs_attention'
    assert len(remote.submissions) == 1


def test_service_review_does_not_expand_exhausted_budget(tmp_path, monkeypatch):
    facade, remote = paused_service(tmp_path, monkeypatch, max_attempts=1)
    result = asyncio.run(facade.resume_mission('mission', acknowledge_uncertain=True,
                                              expected_turn_id='paused-1'))
    assert result['missions']['mission']['status'] == 'failed'
    assert saved_run(facade)['stage'] == 'attempts_exhausted'
    assert len(remote.submissions) == 1


def test_service_review_rechecks_current_model_policy(tmp_path, monkeypatch):
    from mission_control.model_policy import policy_context
    facade, remote = paused_service(tmp_path, monkeypatch)
    model = saved_run(facade)['decision']['model']
    with policy_context(lambda: {model: {'maxEffort': 'low', 'automaticEnabled': False}}):
        result = asyncio.run(facade.resume_mission('mission', acknowledge_uncertain=True,
                                                  expected_turn_id='paused-1'))
    assert result['missions']['mission']['status'] == 'needs_attention'
    assert len(remote.submissions) == 1


def test_service_review_cannot_replace_project_access_approval(tmp_path, monkeypatch):
    facade, remote = paused_service(tmp_path, monkeypatch)
    facade.queue.journal().save('approvals', {})
    with pytest.raises(StateError):
        asyncio.run(facade.resume_mission('mission', acknowledge_uncertain=True,
                                        expected_turn_id='paused-1'))
    assert len(remote.submissions) == 1


def test_restart_rejects_pause_without_matching_terminal_evidence(tmp_path, monkeypatch):
    facade, remote = paused_service(tmp_path, monkeypatch)
    with facade.queue.storage():
        path = Path(facade.queue.read()['missions']['mission']['runPath'])
        run = load_state(path)
        run['attempts'][-1]['pauseReceipt']['terminalConfirmed'] = False
        save_state(path, run)
    result = asyncio.run(facade.resume_mission('mission', acknowledge_uncertain=True,
                                              expected_turn_id='paused-1'))
    assert result['missions']['mission']['status'] == 'needs_attention'
    assert len(remote.submissions) == 1


@pytest.mark.parametrize('quota', ['unknown', 'exhausted'])
def test_reviewed_continuation_rechecks_credit_limits_before_new_submission(tmp_path, monkeypatch, quota):
    import time
    from mission_control.credit_policy import check_credit_limits
    from mission_control.queue import QueueWorker
    from test_credit_policy import limits
    facade, remote = paused_service(tmp_path, monkeypatch)
    remote.limits = None if quota == 'unknown' else limits(100, 10)

    async def credit_gate(model, *, limits=None):
        return check_credit_limits(limits, model, observed_at=time.time())

    remote.credit_gate = credit_gate
    facade.control('resume', 'mission', acknowledge_uncertain=True, expected_turn_id='paused-1')
    result = asyncio.run(QueueWorker(facade.queue, lambda cwd: remote.factory).run(max_wait=0))
    assert result['missions']['mission']['status'] == 'waiting_credit'
    assert len(remote.submissions) == 1
    assert remote.connected == 0
    assert len(saved_run(facade)['attempts']) == 1


@pytest.mark.parametrize('flags', [[], ['--acknowledge-uncertain-result'],
                                  ['--pause-turn-id', 'paused-1']])
def test_cli_resume_requires_both_exact_id_and_explicit_acknowledgement(tmp_path, monkeypatch, flags):
    from mission_control.cli import parser
    from mission_control.queue_cli import execute_queue
    facade, remote = paused_service(tmp_path, monkeypatch)
    args = parser().parse_args(['queue-resume', '--queue', str(facade.queue.path),
                                '--mission-id', 'mission', *flags])
    with pytest.raises(StateError):
        asyncio.run(execute_queue(args))
    assert 'continuationApproved' not in saved_run(facade)['attempts'][-1]
    assert len(remote.submissions) == 1


def test_cli_resume_records_exact_consent_without_starting_codex(tmp_path, monkeypatch):
    from mission_control.cli import parser
    from mission_control.queue_cli import execute_queue
    facade, remote = paused_service(tmp_path, monkeypatch)
    args = parser().parse_args(['queue-resume', '--queue', str(facade.queue.path),
        '--mission-id', 'mission', '--acknowledge-uncertain-result', '--pause-turn-id', 'paused-1'])
    asyncio.run(execute_queue(args))
    assert saved_run(facade)['attempts'][-1]['continuationApproved'] == 'paused-1'
    assert len(remote.submissions) == 1
    assert facade.worker_task is None


@pytest.mark.parametrize('when',['before_review','after_resume_read'])
def test_reviewed_checkpoint_rejects_unreviewed_remote_turns(tmp_path,monkeypatch,when):
    facade,remote=paused_service(tmp_path,monkeypatch)
    extra={'id':'external-turn','status':'completed','itemsView':'full','items':[]}
    if when=='before_review':remote.turns.append(extra)
    else:
        original=remote.read_thread;reads=[0]
        async def changed_history(identity):
            reads[0]+=1
            if reads[0]==2:remote.turns.append(extra)
            return await original(identity)
        remote.read_thread=changed_history
    result=asyncio.run(facade.resume_mission('mission',acknowledge_uncertain=True,expected_turn_id='paused-1'))
    assert result['missions']['mission']['status']=='needs_attention'
    assert len(remote.submissions)==1
