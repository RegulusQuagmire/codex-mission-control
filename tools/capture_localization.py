"""Native Windows RU/EN QA with synthetic data; never starts a backend."""
import json
import os
import sys
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='windows'
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from PySide6.QtCore import QTimer, QPoint
from PySide6.QtWidgets import QApplication, QScrollArea
from test_desktop_gui import Bridge, empty
from test_routing import catalog
from mission_control.desktop.i18n import set_language, tr
from mission_control.desktop.window import MainWindow
from mission_control.desktop.settings import SetupWizard
from mission_control.desktop.missions import MissionDialog, CommandDialog
from mission_control.desktop.approvals import AccessDialog, ResultApprovalDialog, ResultDialog
from mission_control.desktop.tray import DesktopIntegration
from mission_control.desktop.theme import apply_theme
from mission_control.desktop.transfer_dialog import TransferDialog


def main():
    out=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'.local/localization-qa'
    out.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    bridge=Bridge();window=MainWindow(bridge,system_integration=False)
    integration=DesktopIntegration(window,bridge)
    captures=[];errors=[];dialogs=[]
    sys.excepthook=lambda kind,value,trace:errors.append(str(value))
    data=empty();data['models']=catalog();data['connection']={'status':'disconnected','message':'Подключение ещё не проверено'}
    data['preferences'].update(language='ru',setupComplete=True,reducedMotion=True,hotkey='',notifications=False)
    data['limits']['windows']=[{'kind':kind,'limitId':'demo','usedPercent':used,'remainingPercent':100-used,'resetsAt':None} for kind,used in [('five_hour',25),('weekly',40)]]
    job={'id':'demo-review','title':'DEMO','status':'waiting_approval','priority':5,'sequence':0,'dependsOn':[],
         'attempts':[],'model':{'model':'gpt-6-luna','effort':'low'},'project':'C:/DemoProject',
         'dispatchStarted':False,'maxAttempts':3,'type':'text','mode':'balanced','policy':{'mode':'balanced'},
         'task':{'text':'DEMO: 2 + 2'},'expected':'4'}
    data['missions']=[job];data['active']=job['id']
    window.resize(1180,820);window.show()
    steps=[]
    def prepare(lang,theme,small=False):
        data['preferences'].update(language=lang,theme=theme)
        job['title']='ДЕМО: проверка результата' if lang=='ru' else 'DEMO: result review'
        window.update_snapshot(data);integration.update_data(data)
        window.banner.setText('ДЕМО БЕЗ ПОДКЛЮЧЕНИЯ · запросы к модели не выполняются' if lang=='ru' else 'OFFLINE DEMO · no inference requests')
        window.banner.show();window.resize(800,580) if small else window.resize(1180,820)
        window.navigation.setCurrentRow(0)
    def capture(name,widget=window):
        if not widget.grab().save(str(out/(name+'.png'))):raise RuntimeError('Capture failed: '+name)
        captures.append(name+'.png')
    def page(index):window.navigation.setCurrentRow(index)
    def settings():
        page(6);window.settings.findChild(QScrollArea).verticalScrollBar().setValue(0)
    def dialog(kind):
        if kind=='wizard':w=SetupWizard(bridge,data['preferences'])
        elif kind=='mission':w=MissionDialog([],data['preferences'],data['models'])
        elif kind=='command':w=CommandDialog()
        elif kind=='access':w=AccessDialog(job,bridge)
        elif kind=='transfer':w=TransferDialog(bridge,importing=False)
        elif kind=='uncertain-result':
            uncertain=dict(job,status='failed',attempts=[{'phase':'failed','decision':job['model'],
                'validation':{'kind':'not_retryable','passed':False}}])
            w=ResultDialog({'mission':uncertain},bridge)
        else:
            value={'missionId':'demo-review','diff':'DEMO: + example.txt','review':{'spec':{'commands':[]},'reviewId':'demo-review'},'sources':{'example.txt':'DEMO'}}
            w=ResultApprovalDialog(value,bridge)
        dialogs.append(w);w.show()
    for lang in ('ru','en'):
        for theme in ('dark','light'):
            prefix=lang+'-'+theme
            steps.extend([lambda l=lang,t=theme:prepare(l,t),lambda n=prefix+'-dashboard':capture(n)])
            for index,name in ((1,'missions'),(2,'router'),(3,'approvals'),(4,'limits'),(5,'analytics')):
                steps.extend([lambda i=index:page(i),lambda n=prefix+'-'+name:capture(n)])
            steps.extend([settings,lambda n=prefix+'-settings':capture(n)])
            for kind in ('wizard','mission','command','access','result-approval','uncertain-result','transfer'):
                steps.extend([lambda k=kind:dialog(k),lambda n=prefix+'-'+kind:capture(n,dialogs[-1]),lambda:dialogs[-1].close()])
            steps.extend([integration.show_overlay,lambda n=prefix+'-overlay':capture(n,integration.overlay),integration.hide_overlay])
            steps.extend([lambda:integration.tray.contextMenu().popup(QPoint(100,100)),lambda n=prefix+'-tray':capture(n,integration.tray.contextMenu()),lambda:integration.tray.contextMenu().hide()])
            steps.extend([lambda l=lang,t=theme:prepare(l,t,True),lambda n=prefix+'-small-dashboard':capture(n),settings,lambda n=prefix+'-small-settings':capture(n)])
    def advance():
        try:
            if steps:
                steps.pop(0)();QTimer.singleShot(140,advance);return
        except Exception as error:errors.append(str(error))
        integration.closing=True;integration.finished();window.close();app.quit()
    QTimer.singleShot(200,advance);QTimer.singleShot(55000,app.quit);app.exec()
    report={'platform':app.platformName(),'captures':captures,'errors':errors,'backendRequests':bridge.calls,'realInferenceCalls':0}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
    return int(bool(errors) or bool(bridge.calls) or len(captures)!=72)


if __name__=='__main__':raise SystemExit(main())
