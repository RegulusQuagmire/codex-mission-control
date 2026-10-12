"""Find the CLI bundled with Codex without launching it or searching projects."""
import os
from pathlib import Path
import shutil

from ..state import StateError


class CodexNotFound(StateError):
    pass


def resolve_codex(configured='codex'):
    """Explicit choices are authoritative; only the default enables discovery."""
    configured=configured.strip()
    if not configured:
        raise CodexNotFound('Укажите программу Codex или оставьте codex для автоматического поиска.')
    if Path(configured).is_absolute() and Path(configured).is_file():
        return str(Path(configured).resolve())
    found=shutil.which(configured)
    if found and Path(found).is_file():
        return str(Path(found).resolve())
    if configured.casefold() not in {'codex','codex.exe'}:
        raise CodexNotFound('Указанная программа Codex не найдена. Проверьте путь к codex.exe.')
    candidates=[]
    local=os.environ.get('LOCALAPPDATA')
    if local:
        base=Path(local)
        try:
            versions=list((base/'OpenAI/Codex/bin').glob('*/codex.exe'))
            versions.sort(key=lambda path:(path.stat().st_mtime_ns,str(path)),reverse=True)
            candidates.extend(versions)
        except OSError:
            pass
        candidates.extend(base/relative for relative in (
            'Microsoft/WindowsApps/codex.exe','Programs/Codex/resources/codex.exe',
            'Programs/Codex/resources/bin/codex.exe','Programs/Codex/app/resources/codex.exe',
            'Codex/app/resources/codex.exe','Codex/resources/codex.exe'))
    roaming=os.environ.get('APPDATA')
    if roaming:
        npm=Path(roaming)/'npm/node_modules/@openai/codex/vendor'
        candidates.extend(npm/arch/'codex/codex.exe' for arch in ('x86_64-pc-windows-msvc','aarch64-pc-windows-msvc'))
    for variable in ('ProgramFiles','ProgramW6432','ProgramFiles(x86)'):
        folder=os.environ.get(variable)
        if not folder:continue
        base=Path(folder)
        candidates.extend(base/relative for relative in ('Codex/resources/codex.exe','OpenAI/Codex/resources/codex.exe'))
        try:
            packages=sorted((base/'WindowsApps').glob('OpenAI.Codex_*'),reverse=True)
        except OSError:
            packages=[]
        for package in packages:
            candidates.extend(package/relative for relative in ('app/resources/codex.exe','app/resources/bin/codex.exe','resources/codex.exe'))
    for candidate in candidates:
        try:
            if candidate.is_file():return str(candidate.resolve())
        except OSError:
            continue
    raise CodexNotFound('Codex не найден в PATH и стандартных папках установки. Выберите codex.exe в настройках.')
