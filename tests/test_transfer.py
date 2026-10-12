import json
import os
import pytest
from mission_control.state import StateError


def api():
    from mission_control import transfer
    return transfer


def test_transfer_module_exists():
    assert callable(api().export_archive)


def test_archive_roundtrip_sanitized_and_non_executable(tmp_path):
    transfer=api(); path=tmp_path/'portable.cmc'
    result=transfer.export_archive(path,'correct horse battery staple',preferences={'theme':'light','mode':'quality','codex':'unsafe.exe','setupComplete':True,'resumeOnLaunch':True},projects=[{'name':'Demo','path':'C:/demo','commands':['delete']}],history=[{'title':'password=hunter2','status':'done','model':'sample','task':'do not export','threadId':'secret-session','approval':True}])
    assert result['historyCount']==1
    assert b'hunter2' not in path.read_bytes()
    data=transfer.import_archive(path,'correct horse battery staple')
    assert data['trusted'] is False
    assert data['preferences']['theme']=='light'
    assert data['preferences']['codex']=='codex'
    assert data['preferences']['setupComplete'] is False
    assert data['preferences']['resumeOnLaunch'] is False
    assert 'commands' not in data['projects'][0]
    assert 'task' not in data['history'][0] and 'approval' not in data['history'][0]
    assert 'hunter2' not in json.dumps(data)


def test_wrong_password_and_tampering_fail_closed(tmp_path):
    transfer=api(); path=tmp_path/'portable.cmc'
    transfer.export_archive(path,'long enough passphrase',preferences={},projects=[],history=[])
    with pytest.raises(StateError,match='пароль|повреждён'):
        transfer.import_archive(path,'a wrong long passphrase')
    content=bytearray(path.read_bytes()); content[-10]^=1
    altered=tmp_path/'altered.cmc'; altered.write_bytes(content)
    with pytest.raises(StateError):transfer.import_archive(altered,'long enough passphrase')


def test_bounds_password_and_no_overwrite(tmp_path):
    transfer=api(); path=tmp_path/'archive.cmc'; path.write_bytes(b'existing')
    with pytest.raises(StateError):transfer.export_archive(path,'short',preferences={},projects=[],history=[])
    with pytest.raises(StateError):transfer.export_archive(path,'a sufficiently long password',preferences={},projects=[],history=[])
    assert path.read_bytes()==b'existing'
    with pytest.raises(StateError):transfer.import_archive(path,'a sufficiently long password')
    with pytest.raises(StateError):transfer.export_archive(tmp_path/'too-big','a sufficiently long password',preferences={},projects=[],history=[{}]*2001)


def test_hard_link_inputs_rejected(tmp_path):
    transfer=api(); source=tmp_path/'source'; source.write_bytes(b'secret')
    linked=tmp_path/'linked'; os.link(source,linked)
    with pytest.raises(StateError):transfer.import_archive(linked,'a sufficiently long password')


def test_transfer_dialog_requires_matching_password_and_clears_it():
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication, QLineEdit
    from mission_control.desktop.transfer_dialog import TransferDialog
    class Bridge(QObject):
        def __init__(self):super().__init__();self.calls=[]
        def request(self, action, **values):self.calls.append((action,values))
    app=QApplication.instance() or QApplication([]); bridge=Bridge()
    dialog=TransferDialog(bridge)
    assert dialog.password.echoMode()==QLineEdit.Password
    dialog.path.setText('C:/test/archive.cmc')
    dialog.password.setText('a long strong password');dialog.confirm.setText('different password')
    dialog.accept();assert bridge.calls==[]
    dialog.confirm.setText('a long strong password');dialog.accept()
    assert bridge.calls[0][0]=='export_portable'
    assert dialog.password.text()=='' and dialog.confirm.text()==''


def test_transfer_dialog_cancel_does_not_submit():
    from PySide6.QtWidgets import QApplication
    from mission_control.desktop.transfer_dialog import TransferDialog
    class Bridge:
        def request(self,*args,**values):raise AssertionError('Cancel must not submit')
    app=QApplication.instance() or QApplication([])
    dialog=TransferDialog(Bridge(),importing=True)
    dialog.password.setText('a long strong password');dialog.reject()
    assert dialog.password.text()==''


def test_authenticated_import_still_removes_execution_fields(tmp_path):
    import hashlib
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    transfer=api(); salt=b's'*16;nonce=b'n'*12;header=transfer.MAGIC+salt+nonce
    payload={'version':1,'preferences':{'theme':'dark','setupComplete':True,'resumeOnLaunch':True,'codex':'evil.exe','allowedRoots':['C:/']},'projects':[{'path':'../outside','commands':['evil']}],'history':[{'title':'Imported','approval':True,'runPath':'C:/run','threadId':'old','task':'execute'}]}
    key=hashlib.pbkdf2_hmac('sha256',b'a long strong password',salt,transfer.ITERATIONS,dklen=32)
    path=tmp_path/'untrusted.cmc';path.write_bytes(header+AESGCM(key).encrypt(nonce,json.dumps(payload).encode(),header))
    imported=transfer.import_archive(path,'a long strong password')
    assert imported['trusted'] is False
    assert imported['history']==[{'title':'Imported'}]
    assert imported['projects']==[{'path':'../outside'}]  # A suggestion only, never a granted root.
    assert imported['preferences']=={'theme':'dark','codex':'codex','setupComplete':False,'resumeOnLaunch':False}


def test_archive_size_is_bounded_before_key_derivation(tmp_path,monkeypatch):
    transfer=api();path=tmp_path/'oversized.cmc'
    with path.open('wb') as f:f.truncate(transfer.MAX_ARCHIVE+1)
    monkeypatch.setattr(transfer.hashlib,'pbkdf2_hmac',lambda *args,**kwargs:pytest.fail('Oversized input derived a key'))
    with pytest.raises(StateError):transfer.import_archive(path,'a long strong password')


def test_randomized_exports_and_header_integrity(tmp_path):
    transfer=api();one=tmp_path/'one';two=tmp_path/'two'
    for path in (one,two):transfer.export_archive(path,'a long strong password',preferences={},projects=[],history=[])
    assert one.read_bytes()!=two.read_bytes()
    raw=bytearray(one.read_bytes());raw[9]^=1;altered=tmp_path/'altered';altered.write_bytes(raw)
    with pytest.raises(StateError):transfer.import_archive(altered,'a long strong password')


def test_invalid_settings_are_rejected_and_no_archive_created(tmp_path):
    transfer=api();path=tmp_path/'bad'
    for settings in ({'maxAttempts':True},{'maxAttempts':9},{'theme':[]},{'closeToTray':'yes'}):
        with pytest.raises(StateError):transfer.export_archive(path,'a long strong password',preferences=settings,projects=[],history=[])
        assert not path.exists()


def test_import_summary_shows_actual_records_as_plain_text():
    from PySide6.QtWidgets import QApplication, QPlainTextEdit
    from mission_control.desktop.transfer_dialog import PortableSummaryDialog
    app=QApplication.instance() or QApplication([])
    dialog=PortableSummaryDialog({'projects':[{'name':'Example','path':'C:/project/<script>'}],
                                  'history':[{'title':'Actual imported mission','status':'done','model':'model-x','duration':12}]})
    views=[dialog.findChild(QPlainTextEdit,name) for name in ('projects','history')]
    assert len(views)==2 and all(view.isReadOnly() for view in views)
    assert 'Example' in views[0].toPlainText() and 'C:/project/<script>' in views[0].toPlainText()
    assert 'Actual imported mission' in views[1].toPlainText() and 'model-x' in views[1].toPlainText()
    assert not any('execute' in button.text().lower() for button in dialog.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton))


def test_import_summary_bounds_and_filters_display_data():
    from PySide6.QtWidgets import QApplication, QPlainTextEdit
    from mission_control.desktop.transfer_dialog import PortableSummaryDialog
    app=QApplication.instance() or QApplication([])
    dialog=PortableSummaryDialog({'projects':[{'name':'safe','path':'password=hunter2'}]*2001,'history':[]})
    views=[dialog.findChild(QPlainTextEdit,name) for name in ('projects','history')]
    assert 'hunter2' not in views[0].toPlainText()
    assert views[0].toPlainText().count('safe')==2000
    assert 'Нет' in views[1].toPlainText()
