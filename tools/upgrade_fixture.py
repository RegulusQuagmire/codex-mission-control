"""Synthetic old-writer/new-reader QA. Uses only offline test adapters, never Codex."""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys

from mission_control import __version__, safety
from mission_control.desktop.service import DesktopService
from mission_control.queue import MissionQueue, QueueWorker
import mission_control.queue as queue_module
from mission_control.state import StateError
from mission_control.state import load_state

# Select test helpers from the SAME source revision as the imported application.
revision_root=Path(sys.modules['mission_control'].__file__).resolve().parents[2]
sys.path.insert(0,str(revision_root/'tests'))
from test_managed import Service
from test_queue import text_job
from test_validator import spec


def documents(q):
    with sqlite3.connect(q.path) as connection:
        rows=connection.execute('select key,codec from documents order by key').fetchall()
        assert all(codec=='dpapi-user-v1' for _,codec in rows),'Windows DPAPI required'
        assert connection.execute('pragma user_version').fetchone()[0]==1
    return {key:q.journal().load(key) for key,_ in rows}


def worker(q,server):
    queue_module.worker_lease_path=lambda:q.path.parent/'isolated-worker'
    import mission_control.desktop.service as service_module
    service_module.worker_lease_path=queue_module.worker_lease_path
    return QueueWorker(q,lambda cwd:server.factory,clock=lambda:server.now,sleep=server.sleep)


def stage14_seed(q,service,project,case):
    """Create genuine Stage14 receipts through its own service and runner APIs."""
    service.save_preferences({'language':'en','mode':'economy','maxAttempts':4,
        'modelPolicies':{'gpt-6-luna':{'maxEffort':'high','automaticEnabled':True},
                         'gpt-6-astra':{'maxEffort':'low','automaticEnabled':False}},
        'creditPolicy':{'mode':'never','fiveHourReserve':15,'weeklyReserve':20,'paidAcknowledged':False}})
    if case=='waiting_resume':
        from test_stage11_backend_service import PausingService
        server=PausingService();q.add(text_job('paused-turn',project=str(project)))
        safety.approve(q,'paused-turn')
        state=asyncio.run(worker(q,server).run(max_wait=0))
        assert state['missions']['paused-turn']['status']=='waiting_resume'
        q.control('pause')
        return server,{}
    criteria=spec(project);service.configure_roots([criteria['project']])
    service.create_project('upgrade','OFFLINE DAG','Synthetic upgrade graph',criteria['project'],['app.py'])
    commands=[{k:v for k,v in c.items() if k!='approved'} for c in criteria['commands']]
    node={'id':'build','stage':'Implementation','title':'OFFLINE parent','task':'Set VALUE = 2',
          'dependsOn':[],'inputFiles':criteria['inputFiles'],'writeFiles':['app.py'],'commands':commands}
    plan={'version':1,'missions':[node,{**deepcopy(node),'id':'consumer','title':'OFFLINE child','dependsOn':['build']}]}
    service.save_project_plan('upgrade',plan,revision=0)
    review=service.review_project_plan('upgrade')
    service.confirm_project_plan('upgrade',review['reviewId'],acknowledge=True)
    safety.approve(q,'upgrade-build')
    server=Service();server.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    state=asyncio.run(worker(q,server).run(max_wait=0))
    assert state['missions']['upgrade-build']['status']=='waiting_approval'
    result_review=service.review_result('upgrade-build')['review']['reviewId']
    q.control('pause')
    return server,{'resultReviewId':result_review,'projectView':service.project_view('upgrade')}


def seed(root,case):
    if os.name!='nt':raise RuntimeError('Upgrade QA requires Windows DPAPI')
    root.mkdir(parents=True,exist_ok=False)
    project=root/'project';project.mkdir()
    q=MissionQueue(root/'data.sqlite3');service=DesktopService(q);service.initialize()
    service.configure_roots([str(project)])
    service.save_preferences({'theme':'light','reducedMotion':True,'resumeOnLaunch':False})
    server=Service()
    extras={}
    if case in {'waiting_resume','project_dag'}:
        server,extras=stage14_seed(q,service,project,case)
    elif case=='result_approval':
        criteria=spec(project)
        service.configure_roots([criteria['project']])
        q.add({'id':'code','title':'OFFLINE UPGRADE','type':'project','project':criteria['project'],
               'criteria':criteria,'task':{'text':'Synthetic test result only'},'mode':'economy'})
        safety.approve(q,'code')
        server.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
        state=asyncio.run(worker(q,server).run(max_wait=0))
        assert state['missions']['code']['status']=='waiting_approval'
    else:
        q.add(text_job('parent',project=str(project)));safety.approve(q,'parent')
        if case in {'submitted','lost_ack'}:
            server.lose=case=='submitted';server.drop_ack=case=='lost_ack'
        state=asyncio.run(worker(q,server).run(max_wait=0))
        if case=='basic':
            assert state['missions']['parent']['status']=='completed'
            q.add(text_job('dependent',depends=['parent'],project=str(project)))
            q.add(text_job('paused',project=str(project)));q.control('pause','paused');q.control('pause')
        else:assert state['active']=='parent' and len(server.submissions)==1
    baseline=revision_root/'upgrade-baseline.json'
    provenance=json.loads(baseline.read_text(encoding='utf-8')) if baseline.exists() else {}
    before={'version':__version__,'producerRevision':provenance.get('revision'),
            'documents':documents(q),'turns':deepcopy(server.turns),
            'configuration':server.config,'clock':server.now,'preferences':service.preferences(),
            'case':case,'oldMockSubmissions':len(server.submissions),**extras}
    (root/'baseline.json').write_text(json.dumps(before,ensure_ascii=False),encoding='utf-8')
    return {'case':case,'producerVersion':__version__,'producerRevision':before['producerRevision'],
            'oldMockSubmissions':len(server.submissions)}


def verify_stage14(q,service,server,before):
    service.factory_for_cwd=lambda cwd:server.factory
    worker(q,server)  # Isolate both queue and service leases before calling the real facade.
    if before['case']=='waiting_resume':
        job=q.read()['missions']['paused-turn']
        with q.storage():saved=load_state(Path(job['runPath']))
        last=saved['attempts'][-1]
        assert q.read()['paused'] and last['phase']=='paused_turn' and last['turnId']=='paused-1'
        assert last['checkpoint']=='Completed: planning only. Next: answer 2.'
        assert last.get('continuationApproved') is None
        asyncio.run(worker(q,server).run(max_wait=0));assert not server.submissions
        resumed=asyncio.run(service.resume_queue())
        assert resumed['missions']['paused-turn']['status']=='waiting_resume' and not server.submissions
        for consent in ({},{'acknowledge_uncertain':True},{'expected_turn_id':'paused-1'},
                        {'acknowledge_uncertain':True,'expected_turn_id':'stale-turn'}):
            try:asyncio.run(service.resume_mission('paused-turn',**consent))
            except StateError:pass
            else:raise AssertionError('Missing or stale exact-turn consent was accepted')
            assert not server.submissions
            with q.storage():assert load_state(Path(job['runPath']))['attempts'][-1].get('continuationApproved') is None
        server.outcomes=['2']
        result=asyncio.run(service.resume_mission('paused-turn',acknowledge_uncertain=True,expected_turn_id='paused-1'))
        assert result['missions']['paused-turn']['status']=='completed' and len(server.submissions)==1
        with q.storage():completed=load_state(Path(job['runPath']))
        assert completed['attempts'][0]['continuationApproved']=='paused-1'
        assert completed['attempts'][0]['checkpoint']==last['checkpoint']
        try:asyncio.run(service.resume_mission('paused-turn',acknowledge_uncertain=True,expected_turn_id='paused-1'))
        except StateError:pass
        else:raise AssertionError('Completed continuation accepted repeated resume')
        asyncio.run(service.start());assert len(server.submissions)==1
        return {'invalidConsentRejected':4,'continuationTurnId':'paused-1','queuePausePreserved':True,
                'checkpointPreserved':True,'repeatResumeRejected':True}
    view=service.project_view('upgrade')
    assert view==before['projectView'] and view['activated'] and view['revision']==1
    jobs=q.read()['missions']
    assert jobs['upgrade-consumer']['dependsOn']==['upgrade-build']
    assert jobs['upgrade-build']['status']=='waiting_approval' and jobs['upgrade-consumer']['status']=='pending'
    assert view['missions'][1]['blockedBy']==[{'dependency':'upgrade-build','status':'waiting_approval'}]
    safety.authorize(q,jobs['upgrade-build'])
    try:safety.authorize(q,jobs['upgrade-consumer'])
    except StateError:pass
    else:raise AssertionError('Unapproved DAG child acquired project access')
    try:service.approve_result('upgrade-build',before['resultReviewId'],accept_user_rights=True)
    except StateError:pass
    else:raise AssertionError('Old process result review granted execution authority')
    try:service.confirm_project_plan('upgrade',view['reviewId'],acknowledge=True)
    except StateError:pass
    else:raise AssertionError('Already confirmed plan accepted duplicate confirmation')
    asyncio.run(service.resume_queue())
    assert not server.submissions and q.read()['missions']['upgrade-build']['status']=='waiting_approval'
    assert (Path(view['project'])/'app.py').read_text()=='VALUE = 1\n'
    assert service.review_result('upgrade-build')['review']['reviewId']==before['resultReviewId']
    return {'dependenciesPreserved':True,'accessApprovalsPreserved':True,
            'resultApprovalRequired':True,'planAuthorityPreserved':True}


def verify(root):
    before=json.loads((root/'baseline.json').read_text(encoding='utf-8'));case=before['case']
    q=MissionQueue(root/'data.sqlite3');service=DesktopService(q);snapshot=service.initialize()
    current=documents(q)
    assert all(current.get(k)==v for k,v in before['documents'].items()),'Upgrade rewrote protected evidence'
    assert all(service.preferences()[k]==v for k,v in before['preferences'].items()),'Settings changed'
    server=Service();server.turns=before['turns'];server.config=before['configuration']
    server.now=before['clock']+10000;server.outcomes=[]
    details={}
    if case in {'waiting_resume','project_dag'}:
        details=verify_stage14(q,service,server,before)
    elif case in {'submitted','lost_ack'}:
        result=asyncio.run(worker(q,server).run(max_wait=0))
        assert result['missions']['parent']['status']=='completed'
        again=asyncio.run(worker(q,server).run(max_wait=0))
        assert again['missions']['parent']['status']=='completed'
    elif case=='basic':
        assert snapshot['paused'] and q.read()['missions']['paused']['status']=='paused'
        assert q.read()['missions']['dependent']['dependsOn']==['parent']
        try:safety.authorize(q,q.read()['missions']['dependent'])
        except StateError:pass
        else:raise AssertionError('Unapproved child acquired authority')
        q.control('resume','paused')
        assert q.read()['paused'] and q.read()['missions']['paused']['status']=='pending'
    else:
        assert q.read()['missions']['code']['status']=='waiting_approval'
        assert (root/'project/source/app.py').read_text()=='VALUE = 1\n'
        try:service.approve_result('code','unreviewed',accept_user_rights=True)
        except StateError:pass
        else:raise AssertionError('Execution review survived process restart')
    expected=1 if case=='waiting_resume' else 0
    assert len(server.submissions)==expected,'Upgrade resent an existing/unknown operation'
    return {'case':case,'producerVersion':before['version'],'consumerVersion':__version__,
            'producerRevision':before.get('producerRevision'),
            'schema':1,'codec':'dpapi-user-v1','newMockSubmissions':len(server.submissions),'realInference':False,
            'protectedDocumentsPreserved':True,'preferencesPreserved':True,**details}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['seed','verify'])
    parser.add_argument('root',type=Path)
    parser.add_argument('--case',choices=['basic','submitted','lost_ack','result_approval','waiting_resume','project_dag'])
    args=parser.parse_args()
    result=seed(args.root,args.case) if args.phase=='seed' else verify(args.root)
    print(json.dumps(result))


if __name__=='__main__':main()
