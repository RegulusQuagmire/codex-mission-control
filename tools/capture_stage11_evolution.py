"""Native Windows Qt QA with labelled synthetic data and a non-executing bridge.

No account, real queue, Codex process, service or network is accessed. Each Qt
scale runs in a fresh process; OS display settings are never changed.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def worker(out,scale):
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_SCALE_FACTOR']=scale
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtWidgets import QApplication
    from test_desktop_gui import Bridge,empty
    from test_routing import catalog
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.approvals import ResultDialog
    from mission_control.desktop.overlay import MissionOverlay
    from mission_control.desktop.i18n import set_language

    out.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    bridge=Bridge();window=MainWindow(bridge,system_integration=False)
    current={'dialog':None,'overlay':None};steps=[];captures=[];errors=[]
    sys.excepthook=lambda kind,value,trace:errors.append(str(value))

    def value(kind='pending'):
        turn='DEMO-TURN-EXACT-ID'
        checkpoint=('OFFLINE DEMO / ДЕМО БЕЗ INFERENCE\n'
                    'Completed: reviewed the plan only. No project files were read or changed.\n'
                    'Uncertain: check real files, processes and external effects yourself.\n'
                    'Next: continue the same mission after exact-turn review.\n'
                    'Opaque text: Настройки / Settings / {"turnId":"DEMO-TURN-EXACT-ID"}')
        if kind=='empty':checkpoint=''
        if kind=='long':checkpoint=('OFFLINE DEMO · Untrusted descriptive checkpoint; not permission.\n'*250)+checkpoint
        attempt=dict(phase='paused_turn',turnId=turn,checkpoint=checkpoint,
            decision=dict(model='gpt-6-luna',effort='low'),pauseReceipt=dict(
                threadId='DEMO-THREAD-ID',turnId=turn,terminalConfirmed=True,
                phase='terminal_interrupted',reason='user_pause'))
        job=dict(id='demo',title='OFFLINE DEMO · Checkpoint review / Просмотр checkpoint',type='text',
            project='C:/OfflineDemoOnly',task={'text':'DEMO ONLY'},expected='DEMO ONLY',
            status='paused',priority=5,sequence=0,dependsOn=['done'],dispatchStarted=True,
            maxAttempts=3,mode='economy',runPath='DEMO-NONEXECUTABLE',model=attempt['decision'],attempts=[attempt])
        run=dict(stage='waiting_resume',threadId='DEMO-THREAD-ID',attempts=[attempt])
        job['live']=deepcopy(run)
        return dict(mission=job,run=run)

    def snapshot(lang,theme,state='review'):
        data=empty();fixture=value();job=fixture['mission']
        data['preferences'].update(language=lang,theme=theme,reducedMotion=True,
            setupComplete=True,hotkey='',notifications=False)
        data['connection']=dict(status='disconnected',message='OFFLINE DEMO · no account connected')
        data['models']=catalog();data['limitsObservedAt']=None
        data['missions']=[dict(job,id='done',title='DEMO · Completed dependency',status='completed',
            live={},attempts=[],dependsOn=[]),job]
        data.update(active='demo',paused=True)
        attempt=job['live']['attempts'][-1]
        if state in {'running','steer','interrupt','unconfirmed'}:
            job.update(status='running',pauseRequested=False)
            job['live']['stage']='submitted';attempt['phase']='submitted';data['workerRunning']=True
            data['paused']=False
            if state=='running':attempt.pop('pauseReceipt')
            else:attempt['pauseReceipt'].update(terminalConfirmed=False,phase={
                'steer':'steer_requested','interrupt':'interrupt_acknowledged',
                'unconfirmed':'interrupt_unavailable_or_unknown'}[state])
        elif state=='unknown':job['live']['stage']='needs_attention'
        elif state=='authorized':attempt['continuationApproved']=attempt['turnId']
        elif state=='ended':job['live']['stage']='completed_unvalidated';attempt['phase']='completed_unvalidated'
        return data

    def cleanup():
        for key in current:
            widget=current[key]
            if widget:widget.close();widget.deleteLater();current[key]=None

    def prepare(lang,theme,size,page=0,kind=None,state='review'):
        cleanup();data=snapshot(lang,theme,state);window.update_snapshot(data)
        window.setWindowTitle('OFFLINE QA · Codex Mission Control')
        window.banner.setText('ДЕМО · без подключения и запросов к модели' if lang=='ru' else 'OFFLINE DEMO · no connection or model requests')
        window.banner.show();window.resize(*size);window.navigation.setCurrentRow(page)
        if page==1 and window.missions.jobs:window.missions.table.selectRow(1)
        if kind=='overlay':
            overlay=MissionOverlay(bridge,lambda:None);overlay.update_data(data);overlay.show();current['overlay']=overlay
        elif kind:
            fixture=value(kind);set_language(lang)
            dialog=ResultDialog(fixture,bridge,window);dialog.resize(*size);dialog.setWindowTitle('OFFLINE QA · Checkpoint')
            dialog.show();current['dialog']=dialog
            if kind=='reviewed':dialog.pause_consent.setChecked(True)
            if kind=='stale':
                changed=deepcopy(data);changed['missions'][-1]['live']['attempts'][-1]['turnId']='DEMO-CHANGED-TURN'
                bridge.snapshot.emit(changed)
            if kind=='keyboard':dialog.pause_consent.setFocus(Qt.TabFocusReason)

    def capture(name,size,kind):
        widget=current['dialog'] or current['overlay'] or window
        # Windows may constrain the initial show to work-area height. Reapply
        # the requested client geometry after show, without changing OS DPI.
        if kind!='overlay':widget.resize(*size);app.processEvents()
        if kind!='overlay' and (widget.width()!=size[0] or widget.height()!=size[1]):
            errors.append(f'{name}: requested {size}, actual {widget.width()}x{widget.height()}')
        if not widget.grab().save(str(out/(name+'.png'))):raise RuntimeError('PNG capture failed')
        captures.append(dict(file=name+'.png',width=widget.width(),height=widget.height(),
                             dpr=widget.devicePixelRatioF(),keyboardFocus=bool(widget.focusWidget())))

    sizes=[(800,600),(960,740),(1920,1080)] if scale=='1.0' else [(800,600)]
    pages=range(7) if scale=='1.0' else (0,1,3,4)
    for lang in ('ru','en'):
        for theme in ('dark','light'):
            for size in sizes:
                for page in pages:
                    name=f'{lang}-{theme}-{size[0]}x{size[1]}-page{page}'
                    steps += [lambda l=lang,t=theme,s=size,p=page:prepare(l,t,s,p),
                              lambda n=name,s=size:capture(n,s,None)]
                for kind in ('pending','reviewed','empty','long','stale','keyboard'):
                    name=f'{lang}-{theme}-{size[0]}x{size[1]}-{kind}'
                    steps += [lambda l=lang,t=theme,s=size,k=kind:prepare(l,t,s,kind=k),
                              lambda n=name,s=size,k=kind:capture(n,s,k)]
            if scale=='1.0':
                for state in ('running','steer','interrupt','unconfirmed','unknown','authorized','ended'):
                    name=f'{lang}-{theme}-{state}'
                    steps += [lambda l=lang,t=theme,st=state:prepare(l,t,(960,740),state=st),
                              lambda n=name:capture(n,(960,740),None)]
                steps += [lambda l=lang,t=theme:prepare(l,t,(960,740),kind='overlay'),
                          lambda n=f'{lang}-{theme}-overlay':capture(n,(960,740),'overlay')]

    finished=[False]
    def advance():
        if steps:
            try:steps.pop(0)()
            except Exception as error:errors.append(str(error));steps.clear()
            QTimer.singleShot(90,advance)
        else:finished[0]=True;cleanup();window.close();app.quit()
    window.show();QTimer.singleShot(200,advance);QTimer.singleShot(55000,app.quit);app.exec()
    report=dict(platform=app.platformName(),scaleFactor=scale,finished=finished[0],
        captures=captures,errors=errors,backendRequests=bridge.calls,
        data='Explicit synthetic offline fixtures; no account, queue, service or Codex process.',
        scaling='Qt scale factors only; OS DPI unchanged.')
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='captures'},ensure_ascii=True))
    return int(not finished[0] or bool(errors) or bool(bridge.calls) or app.platformName()!='windows')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true')
    parser.add_argument('--scale',default='1.0');parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.worker:return worker(args.out,args.scale)
    for scale in ('1.0','1.25','1.5','2.0'):
        subprocess.run([sys.executable,__file__,'--worker','--scale',scale,
            '--out',str(args.out/('scale-'+scale))],check=True)
    reports=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(args.out.glob('*/report.json'))]
    images=sorted(args.out.glob('*/*.png'))
    import html
    gallery=['<!doctype html><html lang="ru"><meta charset="utf-8"><title>Stage 11 + Evolution · Native Windows QA</title>',
        '<style>body{font:16px Segoe UI;max-width:1200px;margin:24px auto;background:#f3f6fa;color:#172b3e}img{max-width:100%;display:block;margin:12px 0 32px}summary{cursor:pointer;padding:10px}a{color:#006c65}</style>',
        '<h1>Stage 11 + Concept C Evolution</h1><p>Native Windows Qt · RU/EN · Dark/Light · synthetic offline fixtures. No model requests. Qt scaling does not change OS DPI.</p>']
    for image in images:
        relative=image.relative_to(args.out).as_posix();escaped=html.escape(relative)
        gallery.append(f'<details><summary>{escaped}</summary><a href="{escaped}"><img loading="lazy" src="{escaped}" alt="{escaped}"></a></details>')
    (args.out/'index.html').write_text('\n'.join(gallery)+'</html>',encoding='utf-8')
    (args.out/'report.json').write_text(json.dumps(dict(screenshots=len(images),runs=reports),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Native Windows screenshots:',len(images));return 0


if __name__=='__main__':raise SystemExit(main())
