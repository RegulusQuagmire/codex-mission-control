"""Native Windows Router QA, synthetic snapshots and read-only mock inspection."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def worker(out,scale):
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_SCALE_FACTOR']=scale
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtWidgets import QApplication
    from test_desktop_gui import Bridge,empty
    from test_routing import catalog
    from mission_control.desktop.window import MainWindow
    from mission_control.history import History
    from mission_control.route_inspection import inspect_mission
    from mission_control.routing import Complexity
    from mission_control.model_policy import OWNER_PROFILE
    out.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    bridge=Bridge();window=MainWindow(bridge,system_integration=False)
    errors=[];captures=[];steps=[];finished=[False]
    sys.excepthook=lambda kind,value,trace:errors.append(str(value))
    limits={'ordinaryUsageAllowed':True,'rateLimits':{'limitId':'codex',
        'primary':{'usedPercent':1,'windowDurationMins':300},'secondary':{'usedPercent':2,'windowDurationMins':10080}}}

    def prepare(lang,theme,size,kind):
        data=empty();data['preferences'].update(language=lang,theme=theme,reducedMotion=True,setupComplete=True,
            modelPolicies=OWNER_PROFILE,hotkey='',notifications=False)
        data['models']=catalog();data['connection']={'status':'disconnected','message':'OFFLINE DEMO — no account'}
        from mission_control.limits import inspect_limits
        data['limits']=inspect_limits(limits);data['limitsObservedAt']=time.time()
        task={'text':'1. Implement parser.py.\n2. Connect service.py and queue.py with dependencies.\n3. Verify tests and edge cases.\n4. Compare two approaches and explain trade-offs.'}
        if kind in {'history','empty'}:task={'text':'Return only 2','operation':'text'}
        job={'id':'demo','title':'OFFLINE DEMO · Router 2.0','task':task,'type':'text','project':'C:/OFFLINE_DEMO',
            'status':'pending','mode':'balanced','maxAttempts':3,'dependsOn':[],'attempts':[],'expected':'2',
            'priority':0,'sequence':0,'dispatchStarted':False}
        data['missions']=[job];data['routingHistoryRevision']='OFFLINE DEMO'
        history=History()
        if kind=='history':
            for i in range(8):history.record_once(str(i),'gpt-6-luna','low',Complexity.LOW,False)
        if kind=='manual':job['manual']={'model':'gpt-6-astra','effort':'low'}
        if kind=='blocked':data['preferences']['creditPolicy']={'mode':'never','fiveHourReserve':100,'weeklyReserve':100,'paidAcknowledged':False}
        window.update_snapshot(data);window.navigation.setCurrentRow(2)
        window.setWindowTitle('OFFLINE QA · Router 2.0');window.banner.setText('OFFLINE DEMO · NO INFERENCE');window.banner.show()
        value=inspect_mission(data,'demo',history,limits,time.time())
        if kind!='empty':bridge.result.emit('inspect_route',value)
        window.resize(*size);window.show();window.router.preview_button.setFocus(Qt.TabFocusReason)

    def capture(name,size):
        window.resize(*size);app.processEvents()
        if (window.width(),window.height())!=size:errors.append(f'{name}: client size mismatch')
        pixmap=window.grab();pixmap.save(str(out/name))
        captures.append({'file':name,'width':window.width(),'height':window.height(),'dpr':pixmap.devicePixelRatio(),
            'keyboardFocus':window.router.preview_button.hasFocus()})

    def show_details():
        window.pages.currentWidget().verticalScrollBar().setValue(220)
        bar=window.router.recommendation.verticalScrollBar();bar.setValue(bar.maximum())

    for lang in ('ru','en'):
        for theme in ('dark','light'):
            sizes=[(800,600),(960,740),(1920,1080)] if scale=='1.0' else [(800,600)]
            for size in sizes:
                for kind in (('multistep','history','manual','blocked','empty') if size==(800,600) else ('multistep',)):
                    name=f'{lang}-{theme}-{size[0]}x{size[1]}-{kind}.png'
                    steps.extend([lambda l=lang,t=theme,s=size,k=kind:prepare(l,t,s,k),lambda n=name,s=size:capture(n,s)])
                    if scale=='1.0' and size==(800,600) and kind in {'history','blocked'}:
                        detail=name.replace('.png','-details.png')
                        steps.extend([show_details,lambda n=detail,s=size:capture(n,s)])
    def advance():
        if steps:
            try:steps.pop(0)()
            except Exception as error:errors.append(str(error));steps.clear()
            QTimer.singleShot(140,advance)
        else:finished[0]=True;window.close();app.quit()
    QTimer.singleShot(0,advance);app.exec()
    report={'platform':app.platformName(),'scale':scale,'finished':finished[0],'errors':errors,
        'backendRequests':bridge.calls,'captures':captures,'reducedMotion':True,'OSDPIChanged':False}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return int(not finished[0] or bool(errors) or bool(bridge.calls) or app.platformName()!='windows')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--scale',default='1.0');args=parser.parse_args()
    if args.worker:return worker(args.out,args.scale)
    for scale in ('1.0','1.25','1.5','2.0'):
        subprocess.run([sys.executable,__file__,'--worker','--out',str(args.out/('scale-'+scale)),'--scale',scale],check=True)
    reports=[json.loads(p.read_text()) for p in sorted(args.out.glob('*/report.json'))]
    files=sorted(args.out.glob('*/*.png'))
    (args.out/'report.json').write_text(json.dumps({'screenshots':len(files),'runs':reports},indent=2)+'\n',encoding='utf-8')
    from html import escape
    cards=''.join(f'<figure><a href="{p.relative_to(args.out).as_posix()}"><img loading="lazy" src="{p.relative_to(args.out).as_posix()}" style="max-width:100%"></a><figcaption>{escape(str(p.relative_to(args.out)))}</figcaption></figure>' for p in files)
    (args.out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Stage13 Windows Qt offline QA</title><h1>OFFLINE DEMO · Stage13 Router</h1>'+cards,encoding='utf-8')
    print(f'{len(files)} native captures; four Windows Qt scale runs; no backend requests.')
    return 0

if __name__=='__main__':raise SystemExit(main())
