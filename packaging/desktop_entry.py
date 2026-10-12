"""Frozen Windows GUI entry point; never imports the CLI dispatcher."""
if __name__ == '__main__':
    try:
        from mission_control.desktop.app import main
        code=main()
    except Exception as error:
        import sys
        from mission_control.safety import redact
        message=redact(str(error))
        if '--smoke-report' in sys.argv:
            import json
            from mission_control.secure_files import write_file
            target=sys.argv[sys.argv.index('--smoke-report')+1]
            write_file(target,json.dumps({'errors':[message],'startupFailed':True}).encode('utf-8'),new=True)
        else:
            from PySide6.QtWidgets import QApplication,QMessageBox
            app=QApplication.instance() or QApplication([])
            QMessageBox.critical(None,'Mission Control: ошибка запуска',message)
        code=1
    raise SystemExit(code)
