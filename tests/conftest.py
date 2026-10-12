"""Dispose native Qt test windows before QApplication teardown on Windows."""
import sys
import pytest

@pytest.fixture(autouse=True)
def dispose_qt_test_windows():
    yield
    if 'PySide6.QtWidgets' not in sys.modules:return
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication,QEvent
    app=QApplication.instance()
    if app is None:return
    for widget in app.topLevelWidgets():
        widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    app.processEvents()
