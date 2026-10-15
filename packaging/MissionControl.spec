from pathlib import Path
from importlib.metadata import distribution
import sys
import os
import json
from PyInstaller.config import CONF
root = Path(SPECPATH).parent
sys.path.insert(0,str(root/'tools'))
from release_audit import binary_provenance, wheel_owners
from sqlite_release import replace as replace_sqlite
notices=[(str(root/'LICENSE'),'.'),(str(root/'THIRD_PARTY_NOTICES.md'),'.'),
         (str(root/'docs/RELEASE.md'),'docs'),(str(root/'docs/FIRST_RUN.md'),'docs'),
         (str(root/'docs/FIRST_RUN.en.md'),'docs'),(str(root/'packaging/licenses'),'licenses/third-party')]
notices += [(str(root/'docs/LIBRARY_SOURCES.md'),'docs'),
            (str(root/'docs/RELEASE_0.7.1.md'),'docs'),
            (str(root/'packaging/sqlite-runtime.json'),'.')]
notices.append((str(root/'packaging/INSTALLER_LICENSE.txt'),'.'))
notices.append((str(root/'packaging/source-distributions.json'),'.'))
notices.append((str(root/'src/mission_control/desktop/translations.json'),'mission_control/desktop'))
for name in ('PySide6-Essentials','shiboken6','cryptography','cffi','pycparser','pyinstaller','pyinstaller-hooks-contrib'):
    dist=distribution(name)
    for item in dist.files or []:
        relative=str(item).replace('\\','/')
        if '/licenses/' in relative:
            # Preserve nested names: flattening loses distinct vendored LICENSE files.
            tail=Path(relative.split('/licenses/',1)[1])
            notices.append((str(dist.locate_file(item)),'licenses/'+name+'/'+tail.parent.as_posix()))
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if not python_license.exists():raise RuntimeError('Missing CPython license')
notices.append((str(python_license),'licenses/Python'))
a = Analysis([str(root/'packaging/desktop_entry.py')], pathex=[str(root/'src')],
    binaries=[], datas=notices, hiddenimports=['cryptography.hazmat.primitives.ciphers.aead'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtQml','PySide6.QtQuick','pytest','tkinter'],
    noarchive=False)
# Qt Windows wheels use the OS ICU API (unversioned exports). The build Python
# runtime can put a different ICU on PATH; collecting it shadows System32 and
# breaks QtCore at startup. Windows 10 2004+ supplies the required system API.
a.binaries=[item for item in a.binaries if Path(item[0]).name.lower() not in {'icuuc.dll','icudt78.dll'}]
# The application renders Widgets with QPainter; no software OpenGL or image-file
# viewing feature is present. Keep SVG/style support; omit unused codec plugins.
a.binaries=[item for item in a.binaries if Path(item[0]).name.lower()!='opengl32sw.dll'
            and ('/imageformats/' not in item[0].replace('\\','/').lower() or Path(item[0]).name.lower()=='qsvg.dll')]
owners=wheel_owners(root,Path(os.environ['CMC_BUILD_WHEELHOUSE']),Path(os.environ['CMC_BUILD_RUNTIME_ARCHIVE']))
a.binaries,sqlite_owners=replace_sqlite(a.binaries,root,Path(os.environ['CMC_BUILD_SQLITE_ARCHIVE']),Path(CONF['workpath'])/'sqlite-runtime')
owners.update(sqlite_owners)
provenance=binary_provenance(a.binaries,Path(sys.base_prefix),owners)
(Path(CONF['workpath'])/'native-inputs.json').write_text(json.dumps(provenance,indent=2)+'\n')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MissionControl',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    version=str(root/'packaging/version_info.txt'), uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MissionControl')
