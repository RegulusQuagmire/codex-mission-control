import argparse
import os
from pathlib import Path
import sys
import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .bridge import BackendBridge
from .window import MainWindow


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description='Codex Mission Control desktop')
    parser.add_argument('--queue',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'CodexMissionControl'/'missions.sqlite3')
    parser.add_argument('--smoke-report',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--check-codex',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if args.check_codex and not args.smoke_report:parser.error('--check-codex requires --smoke-report')
    return args


def main():
    args=parse_args()
    app=QApplication(sys.argv[:1]);app.setApplicationName('Codex Mission Control')
    from .i18n import set_language
    set_language('ru')
    from .. import __version__
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    bridge=BackendBridge(args.queue);window=MainWindow(bridge,system_integration=not bool(args.smoke_report))
    if args.smoke_report:
        from ..secure_files import write_file
        from ..safety import redact
        # Explicit build QA mode, isolated queue supplied by the release operator.
        window._first_snapshot=False
        report={'version':__version__,'frozen':bool(getattr(sys,'frozen',False)),'errors':[]}
        finished=False
        def finish():
            nonlocal finished
            if finished:return
            finished=True
            data=window.data
            report.update(connection=data.get('connection'),models=len(data.get('models',[])),pages=window.pages.count())
            from .i18n import language, manager
            report.update(language=language(),qtTranslationLoaded=bool(manager.qt_translator),
                          settingsTitle=window.navigation.item(6).text())
            try:write_file(args.smoke_report,json.dumps(report,ensure_ascii=False).encode('utf-8'),new=True)
            except Exception as error:report['errors'].append(redact(str(error)))
            window.close();bridge.request('shutdown')
        bridge.error.connect(lambda message:report['errors'].append(redact(message)))
        bridge.ready.connect(lambda:bridge.request('refresh_connection') if args.check_codex else QTimer.singleShot(350,finish))
        bridge.result.connect(lambda action,value:QTimer.singleShot(350,finish) if action=='refresh_connection' else None)
        bridge.stopped.connect(app.quit)
        deadline=QTimer();deadline.setSingleShot(True);deadline.timeout.connect(lambda:(report['errors'].append('Smoke timeout'),finish()))
        deadline.start(20000)
    window.show();bridge.start()
    code=app.exec()
    if bridge.isRunning():
        bridge.request('shutdown');bridge.wait()
    return (1 if report['errors'] else code) if args.smoke_report else code


if __name__=='__main__':raise SystemExit(main())
