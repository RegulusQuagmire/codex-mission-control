"""Native Windows Qt captures using synthetic plans, no account or backend."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from copy import deepcopy

ROOT=Path(__file__).resolve().parents[1]


def worker(out,scale):
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_SCALE_FACTOR']=scale
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtWidgets import QApplication
    from test_desktop_gui import Bridge,empty
    from test_orchestration import draft
    from mission_control.desktop.projects import ProjectsDialog,PlanReviewDialog,NewProjectDialog
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.i18n import set_language
    from mission_control.desktop.theme import apply_theme
    app=QApplication([]);app.setQuitOnLastWindowClosed(False);app.setProperty('reducedMotion',True)
    bridge=Bridge();errors=[];captures=[];steps=[];current=[None]
    sys.excepthook=lambda kind,value,trace:errors.append(str(value))
    out.mkdir(parents=True,exist_ok=False)
    value={'id':'demo','title':'OFFLINE DEMO · Project Orchestration','goal':'Implement a parser and verify integration',
        'project':'C:/OFFLINE_DEMO','context':{'inputFiles':['README.md']},'revision':1,'reviewId':'offline-exact-review',
        'activated':False,'draft':draft(),'total':0,'completed':0,'missions':[],'planner':None,
        'planningStatus':None,'queuePaused':True}
    value['draft']['missions'].append({**value['draft']['missions'][0],'id':'verify','title':'Verify integration',
        'stage':'Validation','dependsOn':['build'],'task':'Review the implementation and run approved checks. '*12})
    def prepare(lang,theme,size,kind):
        if current[0]:current[0].close();current[0].deleteLater()
        set_language(lang);apply_theme(app,theme)
        data=empty();data['preferences'].update(language=lang,theme=theme,reducedMotion=True,setupComplete=True)
        data['projects']=[value];data['paused']=True
        if kind=='progress':
            progress=deepcopy(value);progress.update(activated=True,total=2,completed=0,missions=[
                {'id':'demo-build','title':'Implement','status':'paused','state':'waiting_resume','blockedBy':[],
                 'accessRequired':False,'stopReason':None},
                {'id':'demo-verify','title':'Verify integration','status':'pending','state':'pending',
                 'blockedBy':[{'dependency':'demo-build','status':'paused'}],'accessRequired':True,'stopReason':None}])
            data['projects']=[progress];widget=ProjectsDialog(bridge,data)
        elif kind=='projects':widget=ProjectsDialog(bridge,data)
        elif kind=='review':widget=PlanReviewDialog(value,bridge)
        elif kind=='create':widget=NewProjectDialog()
        else:
            widget=MainWindow(bridge,system_integration=False);widget.update_snapshot(data);widget.navigation.setCurrentRow(int(kind))
        current[0]=widget;widget.resize(*size);widget.show();widget.raise_()
        if kind=='review':widget.consent.setFocus(Qt.TabFocusReason)
        elif kind=='projects':widget.selector.setFocus(Qt.TabFocusReason)
    def section(index):
        current[0].sections.setCurrentRow(index)
    def capture(name,size):
        widget=current[0];image=widget.grab();image.save(str(out/name))
        if widget.width()>size[0] or widget.height()>size[1]:errors.append('Oversized window: '+name)
        captures.append({'file':name,'width':widget.width(),'height':widget.height(),'dpr':image.devicePixelRatio(),
                         'focus':bool(widget.focusWidget())})
    for lang in ('ru','en'):
        for theme in ('dark','light'):
            sizes=[(800,600),(960,740),(1920,1080)] if scale=='1.0' else [(800,600)]
            for size in sizes:
                for kind in ('projects','review','create','progress'):
                    name=f'{lang}-{theme}-{size[0]}x{size[1]}-{kind}.png'
                    steps += [lambda l=lang,t=theme,s=size,k=kind:prepare(l,t,s,k),lambda n=name,s=size:capture(n,s)]
                    if kind=='review' and scale=='1.0' and size==(800,600):
                        for index in (1,2,3):
                            name=f'{lang}-{theme}-800x600-review-section-{index}.png'
                            steps += [lambda i=index:section(i),lambda n=name:capture(n,(800,600))]
            if scale=='1.0':
                for page in range(7):
                    name=f'{lang}-{theme}-960x740-screen-{page}.png'
                    steps += [lambda l=lang,t=theme,k=str(page):prepare(l,t,(960,740),k),lambda n=name:capture(n,(960,740))]
    def advance():
        if steps:
            try:steps.pop(0)()
            except Exception as error:errors.append(str(error));steps.clear()
            QTimer.singleShot(120,advance)
        else:
            if current[0]:current[0].close()
            app.quit()
    QTimer.singleShot(0,advance);app.exec()
    report={'platform':app.platformName(),'scale':scale,'errors':errors,'backendRequests':bridge.calls,
            'captures':captures,'reducedMotion':True,'OSDPIChanged':False}
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return int(bool(errors) or bool(bridge.calls) or app.platformName()!='windows')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--scale',default='1.0');args=parser.parse_args()
    if args.worker:return worker(args.out,args.scale)
    for scale in ('1.0','1.25','1.5','2.0'):
        subprocess.run([sys.executable,__file__,'--worker','--out',str(args.out/('scale-'+scale)),'--scale',scale],check=True)
    reports=[json.loads(p.read_text()) for p in sorted(args.out.glob('*/report.json'))]
    files=sorted(args.out.glob('*/*.png'))
    (args.out/'report.json').write_text(json.dumps({'screenshots':len(files),'runs':reports},indent=2),encoding='utf-8')
    from html import escape
    cards=''.join(f'<figure><img loading="lazy" src="{p.relative_to(args.out).as_posix()}" style="max-width:100%"><figcaption>{escape(p.name)}</figcaption></figure>' for p in files)
    (args.out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Stage14 native Windows QA</title><h1>OFFLINE DEMO</h1>'+cards,encoding='utf-8')
    print(f'{len(files)} native Windows captures; no backend requests.')
    return 0


if __name__=='__main__':raise SystemExit(main())
