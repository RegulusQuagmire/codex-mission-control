"""Offline native Windows QA, scale-factor matrix and process measurements.

Uses synthetic snapshots and the test bridge only. Never starts Codex/App Server.
QT_SCALE_FACTOR exercises Qt scaling without changing Windows display settings.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]


def worker(out,scale):
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_SCALE_FACTOR']=scale
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from test_desktop_gui import Bridge,empty
    from test_routing import catalog
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.theme import apply_theme
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    bridge=Bridge();window=MainWindow(bridge,system_integration=False)
    captures=[];errors=[];steps=[];timings={};heartbeat=[]
    sys.excepthook=lambda kind,value,trace:errors.append(str(value))
    out.mkdir(parents=True,exist_ok=True)
    def job(identity='demo',status='pending',**values):
        return dict(id=identity,title='DEMO · Mission '+identity,project='C:/DemoProject',status=status,
            priority=5,sequence=0,dependsOn=[],dispatchStarted=False,attempts=[],maxAttempts=3,
            type='text',mode='balanced',model={'model':'gpt-6-luna','effort':'low'},**values)
    def snapshot(lang,theme,scenario='approval'):
        data=empty();data['connection']={'status':'connected','message':'Codex подключён'};data['models']=catalog()
        data['preferences'].update(language=lang,theme=theme,reducedMotion=True,setupComplete=True,hotkey='',notifications=False)
        data['limitsObservedAt']=time.time()
        data['limits']['windows']=[dict(kind=kind,limitId='demo',usedPercent=used,remainingPercent=100-used,resetsAt=None) for kind,used in [('five_hour',25),('weekly',40)]]
        data['missions']=[job(status='waiting_approval')];data['active']='demo'
        if scenario=='disconnected':data.update(connection={'status':'disconnected','message':'Подключение ещё не проверено'},models=[],missions=[],active=None)
        elif scenario=='no-models':data['models']=[]
        elif scenario=='unknown-limits':data['limits']={'windows':[]};data['limitsObservedAt']=None
        elif scenario=='exhausted':
            for item in data['limits']['windows']:item.update(remainingPercent=0,usedPercent=100)
            data['missions'][0].update(status='waiting_limit',live={'stage':'waiting_limit','waitReason':'Weekly budget reached'})
        elif scenario=='large-queue':
            data['missions']=[job(str(i)) for i in range(1000)];data['active']=None
        elif scenario=='empty':data.update(missions=[],active=None)
        elif scenario=='failed':data['missions'][0]['status']='failed'
        elif scenario=='uncertain':data['missions'][0]['status']='needs_attention'
        elif scenario=='paused':data['missions'][0]['status']='running';data['paused']=True
        elif scenario=='cancel-requested':data['missions'][0].update(status='running',cancelRequested=True)
        elif scenario=='stale':data['limitsObservedAt']=time.time()-900
        return data
    def prepare(lang,theme,size,scenario='approval',page=0):
        data=snapshot(lang,theme,scenario)
        started=time.perf_counter();window.update_snapshot(data)
        if scenario=='large-queue':timings['largeQueueSnapshotMs']=(time.perf_counter()-started)*1000
        window.banner.setText('ДЕМО · без запросов к модели' if lang=='ru' else 'OFFLINE DEMO · no model requests');window.banner.show()
        window.resize(*size);window.navigation.setCurrentRow(page)
        if page==1 and window.missions.jobs:window.missions.table.selectRow(0)
    def capture(name):
        if not window.grab().save(str(out/(name+'.png'))):raise RuntimeError('Capture failed')
        captures.append(name+'.png')
    window.show()
    sizes=[(800,600),(960,740),(1920,1080)] if scale=='1.0' else [(800,600)]
    pages=list(range(7)) if scale=='1.0' else [0,2,6]
    for lang in ('ru','en'):
        for theme in ('dark','light'):
            for size in sizes:
                for page in pages:
                    name=f'{lang}-{theme}-{size[0]}x{size[1]}-page{page}'
                    steps.extend([lambda l=lang,t=theme,s=size,p=page:prepare(l,t,s,page=p),lambda n=name:capture(n)])
    if scale=='1.0':
        for lang,theme in [('ru','dark'),('en','light')]:
            for scenario in ('disconnected','no-models','unknown-limits','exhausted','large-queue','empty','failed','uncertain','paused','cancel-requested','stale'):
                page=1 if scenario=='large-queue' else 4 if scenario in ('unknown-limits','exhausted','stale') else 0
                steps.extend([lambda l=lang,t=theme,s=scenario,p=page:prepare(l,t,(1180,820),s,p),lambda n=lang+'-'+theme+'-'+scenario:capture(n)])
    def advance():
        if steps:
            try:steps.pop(0)()
            except Exception as error:errors.append(str(error));steps.clear()
            QTimer.singleShot(75,advance)
        else:begin_idle()
    last=[time.perf_counter()]
    def tick():
        now=time.perf_counter();heartbeat.append((now-last[0])*1000);last[0]=now
    timer=QTimer();timer.setInterval(25);timer.timeout.connect(tick)
    baseline={}
    def begin_idle():
        prepare('ru','dark',(1180,820),'empty');QTimer.singleShot(1000,measure_idle)
    def measure_idle():
        baseline.update(cpu=time.process_time(),wall=time.perf_counter())
        last[0]=time.perf_counter();timer.start();QTimer.singleShot(4000,finish)
    def finish():
        timer.stop();timings['idleCpuPercentOneCore']=100*(time.process_time()-baseline['cpu'])/(time.perf_counter()-baseline['wall'])
        timings['maxHeartbeatMs']=max(heartbeat,default=0)
        class Memory(ctypes.Structure):
            _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in ('peakWorkingSet','workingSet','peakPagedPool','pagedPool','peakNonPagedPool','nonPagedPool','pagefile','peakPagefile')]
        memory=Memory();memory.cb=ctypes.sizeof(memory)
        kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
        psapi=ctypes.windll.psapi;psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(memory),memory.cb):
            timings.update(workingSetMiB=memory.workingSet/1048576,peakWorkingSetMiB=memory.peakWorkingSet/1048576)
        window.close();app.quit()
    QTimer.singleShot(200,advance);QTimer.singleShot(60000,app.quit);app.exec()
    screen=app.primaryScreen()
    report=dict(platform=app.platformName(),scaleFactor=scale,devicePixelRatio=screen.devicePixelRatio(),
        logicalDpi=screen.logicalDotsPerInch(),physicalDpi=screen.physicalDotsPerInch(),captures=captures,
        errors=errors,backendRequests=bridge.calls,measurements=timings)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
    return int(bool(errors) or bool(bridge.calls) or not captures or 'idleCpuPercentOneCore' not in timings)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');parser.add_argument('--scale',default='1.0')
    parser.add_argument('--out',type=Path,default=ROOT/'.local/stage12-qa');args=parser.parse_args()
    if args.worker:return worker(args.out,args.scale)
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'))
    subprocess.run([sys.executable,str(ROOT/'tools/capture_localization.py'),str(args.out/'base')],env=env,check=True)
    for scale in ('1.0','1.25','1.5','2.0'):
        subprocess.run([sys.executable,__file__,'--worker','--scale',scale,'--out',str(args.out/('scale-'+scale))],env=env,check=True)
    reports=[json.loads(path.read_text(encoding='utf-8')) for path in args.out.glob('*/report.json')]
    assert all(not r['errors'] and not r['backendRequests'] for r in reports)
    images=sorted(args.out.glob('*/*.png'))
    html='<html lang="ru"><meta charset="utf-8"><title>Stage 12 · Native Windows QA</title><style>body{font:16px Segoe UI;background:#0c121b;color:#eef;padding:24px}a{color:#7dc}img{max-width:100%;display:block;margin-bottom:30px}</style><h1>Concept C Evolution · Windows GUI</h1><p>Offline synthetic data. Qt scale factors do not change OS display settings.</p>'
    for path in images:
        relative=path.relative_to(args.out).as_posix();html+=f'<h2>{relative}</h2><a href="{relative}"><img loading="lazy" src="{relative}"></a>'
    (args.out/'index.html').write_text(html+'</html>',encoding='utf-8')
    (args.out/'report.json').write_text(json.dumps({'screenshots':len(images),'runs':reports},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Native screenshots:',len(images));return 0


if __name__=='__main__':raise SystemExit(main())
