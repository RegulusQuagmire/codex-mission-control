import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialogButtonBox

def test_mission_and_command_dialog_buttons_are_russian():
    from mission_control.desktop.missions import MissionDialog,CommandDialog
    app=QApplication.instance() or QApplication([])
    for dialog,accept in ((MissionDialog([],{},[]),QDialogButtonBox.Save),(CommandDialog(),QDialogButtonBox.Ok)):
        buttons=dialog.findChild(QDialogButtonBox)
        assert buttons.button(accept).text() in {'Сохранить','Добавить'}
        assert buttons.button(QDialogButtonBox.Cancel).text()=='Отмена'
        dialog.close()
