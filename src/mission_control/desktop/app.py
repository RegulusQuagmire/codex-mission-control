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
    default_queue=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'CodexMissionControl'/'missions.sqlite3'
    parser.add_argument('--queue',type=Path,default=default_queue)
    parser.add_argument('--smoke-report',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--check-codex',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--smoke-language',choices=['ru','en'],help=argparse.SUPPRESS)
    parser.add_argument('--smoke-theme',choices=['dark','light'],help=argparse.SUPPRESS)
    parser.add_argument('--smoke-size',choices=['800x600','960x740','1920x1080'],help=argparse.SUPPRESS)
    parser.add_argument('--smoke-screenshots',type=Path,help=argparse.SUPPRESS)
    raw=list(sys.argv[1:] if argv is None else argv)
    args=parser.parse_args(raw)
    if args.check_codex and not args.smoke_report:parser.error('--check-codex requires --smoke-report')
    if any((args.smoke_language,args.smoke_theme,args.smoke_size,args.smoke_screenshots)) and not args.smoke_report:
        parser.error('Smoke options require --smoke-report')
    if args.smoke_report:
        if not any(a=='--queue' or a.startswith('--queue=') for a in raw) or args.queue.resolve()==default_queue.resolve():
            parser.error('Smoke QA requires an explicit disposable --queue outside the default user database')
        if args.smoke_report.resolve()==args.queue.resolve():parser.error('Report must not overwrite the queue')
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
        report={'version':__version__,'frozen':bool(getattr(sys,'frozen',False)),
                'qtPlatform':app.platformName(),'errors':[]}
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
            if args.smoke_screenshots:
                try:
                    from .theme import apply_theme
                    from .settings import SetupWizard
                    from PySide6.QtGui import QGuiApplication
                    from PySide6.QtCore import QCoreApplication
                    preferences={**data.get('preferences',{}),'language':args.smoke_language or 'ru',
                                 'theme':args.smoke_theme or 'dark','reducedMotion':True,'resumeOnLaunch':False}
                    window.update_snapshot({**data,'preferences':preferences})
                    set_language(preferences['language'])
                    apply_theme(app,preferences['theme'])
                    window.set_reduced_motion(True)
                    width,height=map(int,(args.smoke_size or '960x740').split('x'))
                    # Windows can clamp oversized native windows after processing
                    # WM_GETMINMAXINFO. Force the requested QA client size explicitly.
                    window.setMinimumSize(width,height)
                    window.resize(width,height)
                    QCoreApplication.processEvents();window.resize(width,height);QCoreApplication.processEvents()
                    if (window.width(),window.height())!=(width,height):
                        raise RuntimeError('Native window cannot reach requested QA client size')
                    args.smoke_screenshots.mkdir(parents=True,exist_ok=False)
                    frames=[]
                    for index in range(window.pages.count()):
                        window.navigation.setCurrentRow(index);QCoreApplication.processEvents()
                        target=args.smoke_screenshots/f'page-{index}.png'
                        pixmap=window.grab()
                        expected=(round(width*window.devicePixelRatioF()),round(height*window.devicePixelRatioF()))
                        if (pixmap.width(),pixmap.height())!=expected:raise RuntimeError('GUI screenshot dimensions mismatch')
                        if not pixmap.save(str(target)):raise RuntimeError('Cannot save GUI screenshot')
                        frames.append(target.name)
                    wizard=SetupWizard(bridge,data.get('preferences',{}),window)
                    wizard.show();QCoreApplication.processEvents()
                    if not wizard.grab().save(str(args.smoke_screenshots/'onboarding.png')):
                        raise RuntimeError('Cannot save onboarding screenshot')
                    wizard.reject();wizard.deleteLater()
                    report.update(screenshots=frames+['onboarding.png'],language=language(),
                                  qtTranslationLoaded=bool(manager.qt_translator),
                                  settingsTitle=window.navigation.item(6).text(),
                                  settingsTheme=window.settings.theme.currentData(),
                                  settingsReducedMotion=window.settings.reduced_motion.isChecked(),
                                  theme=args.smoke_theme or 'dark',size=[width,height],
                                  qtPlatform=QGuiApplication.platformName(),devicePixelRatio=window.devicePixelRatioF(),
                                  reducedMotion=True)
                except Exception as error:report['errors'].append(redact(str(error)))
            try:write_file(args.smoke_report,json.dumps(report,ensure_ascii=False).encode('utf-8'),new=True)
            except Exception as error:report['errors'].append(redact(str(error)))
            window.close();bridge.request('shutdown')
        bridge.error.connect(lambda message:report['errors'].append(redact(message)))
        bridge.ready.connect(lambda:bridge.request('refresh_connection') if args.check_codex else QTimer.singleShot(350,finish))
        bridge.result.connect(lambda action,value:QTimer.singleShot(350,finish) if action=='refresh_connection' else None)
        def backend_stopped():
            if not finished:
                report['errors'].append('Backend stopped before smoke completion');finish()
            app.quit()
        bridge.stopped.connect(backend_stopped)
        deadline=QTimer();deadline.setSingleShot(True);deadline.timeout.connect(lambda:(report['errors'].append('Smoke timeout'),finish()))
        deadline.start(20000)
    window.show();bridge.start()
    code=app.exec()
    if bridge.isRunning():
        bridge.request('shutdown');bridge.wait()
    return (1 if report['errors'] else code) if args.smoke_report else code


if __name__=='__main__':raise SystemExit(main())
