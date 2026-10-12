from pathlib import Path
from importlib.metadata import distribution
import sys
root = Path(SPECPATH).parent
notices=[(str(root/'LICENSE'),'.'),(str(root/'THIRD_PARTY_NOTICES.md'),'.'),
         (str(root/'docs/RELEASE.md'),'docs'),(str(root/'packaging/licenses'),'licenses/Qt')]
for name in ('PySide6-Essentials','shiboken6','cryptography','cffi','pyinstaller'):
    dist=distribution(name)
    for item in dist.files or []:
        if '/licenses/' in str(item).replace('\\','/'):
            notices.append((str(dist.locate_file(item)),'licenses/'+name))
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():notices.append((str(python_license),'licenses/Python'))
a = Analysis([str(root/'packaging/desktop_entry.py')], pathex=[str(root/'src')],
    binaries=[], datas=notices, hiddenimports=['cryptography.hazmat.primitives.ciphers.aead'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtQml','PySide6.QtQuick','pytest','tkinter'],
    noarchive=False)
# Qt Windows wheels use the OS ICU API (unversioned exports). The build Python
# runtime can put a different ICU on PATH; collecting it shadows System32 and
# breaks QtCore at startup. Windows 10 2004+ supplies the required system API.
a.binaries=[item for item in a.binaries if Path(item[0]).name.lower() not in {'icuuc.dll','icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MissionControl',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    version=str(root/'packaging/version_info.txt'), uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MissionControl')
