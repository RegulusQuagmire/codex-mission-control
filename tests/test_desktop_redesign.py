"""Behavioral checks for the real snapshot-driven presentation."""
import pytest
from PySide6.QtCore import Qt,QAbstractAnimation,QEvent,QCoreApplication
from PySide6.QtTest import QTest
from test_desktop_gui import app,Bridge,empty,qt_slot_exceptions


def test_graph_never_invents_catalog_or_activity(app):
    from mission_control.desktop.visuals import RouterNetwork
    network=RouterNetwork();network.set_snapshot(empty())
    assert network.models==[] and network.selected is None
    assert network.pulse.state()==QAbstractAnimation.Stopped
    data=empty();data['models']=[{'model':'available','displayName':'Available'}]
    data['active']='a';data['workerRunning']=True
    data['missions']=[{'id':'a','title':'A','status':'running','model':{'model':'actual','effort':'high','reason':'Real reason'}}]
    network.set_snapshot(data)
    assert network.selected=='actual' and 'actual' in [m['model'] for m in network.models]
    network.pulse.setDuration(70);QTest.qWait(130)
    assert network.pulse.state()==QAbstractAnimation.Stopped
    network.set_snapshot(data);assert network.pulse.state()==QAbstractAnimation.Stopped
    data['workerRunning']=False;network.set_snapshot(data)
    assert network.pulse.state()==QAbstractAnimation.Stopped
    data['workerRunning']=True;network.set_snapshot(data)
    assert network.pulse.state()==QAbstractAnimation.Running
    data['workerRunning']=False;network.set_snapshot(data)
    assert network.pulse.state()==QAbstractAnimation.Stopped
    network.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)


def test_real_dashboard_composition_and_reduced_motion(app):
    from mission_control.desktop.window import MainWindow
    window=MainWindow(Bridge(),system_integration=False);window.show()
    data=empty();window.update_snapshot(data);app.processEvents()
    assert not window.network.models
    assert 'Нет данных' in window.limit_summary.text()
    assert window.mission_title.text()=='Нет активной миссии'
    window.set_reduced_motion(True)
    assert window.network.reduced_motion
    for index in range(window.pages.count()):
        window.navigation.setCurrentRow(index);app.processEvents()
        assert window.page_animation.state()==QAbstractAnimation.Stopped
    window.resize(800,600);app.processEvents();assert window.width()==800
    window.close();window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)


def test_wizard_ignores_unrelated_errors_and_stale_results(app,tmp_path):
    from mission_control.desktop.settings import SetupWizard
    wizard=SetupWizard(Bridge(),{});wizard.show();wizard.next();wizard.root.setText(str(tmp_path));wizard.accept()
    token=wizard.bridge.calls[-1][1].get('_request_token')
    wizard.bridge.error.emit('Unrelated worker error')
    assert wizard._pending=='complete_setup'
    wizard.bridge.result.emit('complete_setup',{'status':'connected','message':'Old response','_requestToken':'stale'})
    assert wizard.isVisible() and wizard._pending=='complete_setup'
    wizard.bridge.result.emit('complete_setup',{'status':'connected','message':'Connected','_requestToken':token})
    assert not wizard.isVisible()
    wizard.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)


def test_overlay_toggles_reuse_animation(app):
    from mission_control.desktop.overlay import MissionOverlay
    from PySide6.QtCore import QPropertyAnimation
    overlay=MissionOverlay(Bridge(),lambda:None);overlay.show();app.processEvents()
    for index in range(20):overlay.toggle_compact()
    assert len(overlay.network.findChildren(QPropertyAnimation))<=2
    overlay.close();overlay.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)


@pytest.mark.parametrize('theme',['dark','light'])
def test_semantic_contrast(theme):
    from mission_control.desktop.theme import TOKENS
    # A self-contained luminance calculation; does not import demo widgets.
    def luminance(value):
        values=[int(value[i:i+2],16)/255 for i in (1,3,5)]
        return sum((v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4)*k for v,k in zip(values,(.2126,.7152,.0722)))
    p=TOKENS[theme]
    for fg,bg in [('text','bg'),('muted','surface'),('warning','surface'),('bg','accent')]:
        low,high=sorted((luminance(p[fg]),luminance(p[bg])))
        assert (high+.05)/(low+.05)>=4.5


def test_quota_unknown_and_reduced_motion(app):
    from mission_control.desktop.visuals import QuotaTelemetry
    meter=QuotaTelemetry();meter.set_data({'windows':[]},True)
    assert meter.windows==[] and meter.motion.state()==QAbstractAnimation.Stopped
    meter.set_data({'windows':[{'kind':'weekly','limitId':'codex','remainingPercent':None,'usedPercent':None}]},True)
    meter.show();app.processEvents();assert meter.grab().width()>0
    assert meter.settle==1. and meter.motion.state()==QAbstractAnimation.Stopped
    meter.close()


def test_setup_backend_not_ready_is_retryable(app,tmp_path):
    from mission_control.desktop.settings import SetupWizard
    from mission_control.desktop.bridge import BackendBridge
    from PySide6.QtWidgets import QWizard
    bridge=BackendBridge(tmp_path/'never-started.sqlite3')
    wizard=SetupWizard(bridge,{});wizard.show();wizard.next();wizard.check()
    assert wizard._pending is None
    assert wizard.button(QWizard.CancelButton).isEnabled()
    assert 'готов' in wizard.status.text()
    wizard.close()


def test_overlay_restores_compact_preference_before_first_show(app):
    from mission_control.desktop.overlay import MissionOverlay
    data=empty();data['preferences']['overlayCompact']=True
    overlay=MissionOverlay(Bridge(),lambda:None);overlay.update_data(data)
    assert overlay.compact and overlay.network.maximumHeight()==0
    assert overlay.details.isHidden()
    overlay.set_reduced_motion(True);overlay.toggle_compact()
    assert not overlay.compact and overlay.network.maximumHeight()==130
    overlay.close()


def test_bridge_ready_means_event_loop_accepts_requests(app,tmp_path):
    from mission_control.desktop.bridge import BackendBridge
    from test_desktop_gui import wait_until
    bridge=BackendBridge(tmp_path/'ready.sqlite3');observed=[]
    bridge.ready.connect(lambda:observed.append(bridge.loop.is_running()),Qt.DirectConnection)
    bridge.start()
    try:
        wait_until(app,lambda:bool(observed))
        assert observed==[True]
    finally:
        bridge.request('shutdown');wait_until(app,lambda:not bridge.isRunning())
