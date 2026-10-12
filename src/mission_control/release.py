"""Offline, information-only update metadata. Never downloads or executes code."""
import json
import re
from urllib.parse import urlsplit
from . import __version__
from .secure_files import read_file
from .state import StateError
from .safety import reject_secrets


def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})',value):
        raise StateError('Некорректная версия релиза')
    return tuple(map(int,value.split('.')))


def inspect_manifest(path):
    raw=read_file(path,limit=65536)
    try:data=json.loads(raw) if raw else None
    except (ValueError,UnicodeError,RecursionError):raise StateError('Некорректное описание обновления') from None
    if not isinstance(data,dict) or set(data)-{'version','notes','url','sha256'}:
        raise StateError('Неизвестные поля описания обновления')
    target=version_tuple(data.get('version'));reject_secrets(data)
    notes=data.get('notes','')
    if not isinstance(notes,str) or len(notes)>10000:raise StateError('Слишком длинное описание')
    url=data.get('url','')
    if url:
        if not isinstance(url,str) or len(url)>2048:raise StateError('Некорректная ссылка')
        try:parsed=urlsplit(url)
        except ValueError:raise StateError('Некорректная ссылка') from None
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or any(ord(c)<33 for c in url):
            raise StateError('Допускается только HTTPS без учётных данных')
    digest=data.get('sha256','')
    if digest and (not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest)):
        raise StateError('Некорректная контрольная сумма')
    return {'version':data['version'],'current':__version__,'newer':target>version_tuple(__version__),
            'notes':notes,'url':url,'sha256':digest,'trusted':False,'automaticInstall':False}
