"""Capture actual Qt widgets with labelled offline fixtures; no backend or inference."""
import json
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'windows'
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QScrollArea
from test_desktop_gui import Bridge, empty
from test_routing import catalog
from mission_control.desktop.window import MainWindow
from mission_control.desktop.overlay import MissionOverlay


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'docs/images'
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge()
    window = MainWindow(bridge, system_integration=False)
    window.resize(1200, 850)
    data = empty()
    data['connection'] = {'status': 'error', 'message': 'OFFLINE DEMO — synthetic data, no account connected'}
    data['models'] = catalog()
    data['preferences'].update(setupComplete=True, reducedMotion=True,
        creditPolicy={'mode': 'never', 'fiveHourReserve': 15, 'weeklyReserve': 20, 'paidAcknowledged': False},
        modelPolicies={})
    data['limits']['windows'] = [
        {'kind': 'five_hour', 'limitId': 'demo', 'usedPercent': 25, 'remainingPercent': 75, 'resetsAt': None},
        {'kind': 'weekly', 'limitId': 'demo', 'usedPercent': 40, 'remainingPercent': 60, 'resetsAt': None}]
    data['missions'] = [
        {'id': 'demo-review', 'title': 'DEMO: Review generated changes', 'status': 'waiting_approval',
         'priority': 5, 'sequence': 0, 'dependsOn': [], 'attempts': [],
         'model': {'model': 'gpt-6-luna', 'effort': 'low'}},
        {'id': 'demo-docs', 'title': 'DEMO: Update documentation', 'status': 'pending',
         'priority': 3, 'sequence': 1, 'dependsOn': ['demo-review'], 'attempts': []},
        {'id': 'demo-tests', 'title': 'DEMO: Review test results', 'status': 'pending',
         'priority': 2, 'sequence': 2, 'dependsOn': [], 'attempts': []}]
    data['active'] = 'demo-review'
    for mission in data['missions']:
        mission.update(project='C:/DemoProject', dispatchStarted=False, maxAttempts=3)
    window.update_snapshot(data)
    window.banner.setText('OFFLINE DEMO · synthetic catalog, quota and missions · no real inference')
    window.banner.show()
    overlay = MissionOverlay(bridge, lambda: None)
    overlay.update_data(data)
    overlay.header.setText('OFFLINE DEMO · MISSION CONTROL')
    names = []
    errors = []
    sys.excepthook = lambda kind, value, trace: errors.append(str(value))
    steps = []
    def page(index):
        window.navigation.setCurrentRow(index)
    def capture(name, widget=window):
        if not widget.grab().save(str(out / name)):
            raise RuntimeError('Capture failed: ' + name)
        names.append(name)
    for name, index in [('dashboard.png', 0), ('mission-queue.png', 1), ('smart-router.png', 2),
                        ('security-approval.png', 3), ('limit-manager.png', 4)]:
        steps.extend([lambda index=index: page(index), lambda name=name: capture(name)])
    def settings(model_policy):
        page(6)
        scroll = window.settings.findChild(QScrollArea)
        scroll.ensureWidgetVisible(window.settings.model_policies if model_policy else window.settings.credit_policy)
    steps.extend([lambda: settings(False), lambda: capture('credit-policy.png'),
                  lambda: settings(True), lambda: capture('model-policy.png'),
                  overlay.show, lambda: capture('overlay.png', overlay)])
    def advance():
        try:
            if steps:
                steps.pop(0)()
                QTimer.singleShot(350, advance)
                return
            assert not bridge.calls, 'Demo must never request backend work'
            assert app.platformName() == 'windows'
        except Exception as error:
            errors.append(str(error))
        overlay.close()
        window.close()
        app.quit()
    window.show()
    QTimer.singleShot(350, advance)
    QTimer.singleShot(20000, app.quit)
    app.exec()
    print(json.dumps({'qpa': app.platformName(), 'captures': names, 'backendRequests': len(bridge.calls),
                      'realInferenceCalls': 0, 'errors': errors}))
    return int(bool(errors) or len(names) != 8 or bool(bridge.calls))


if __name__ == '__main__':
    raise SystemExit(main())
