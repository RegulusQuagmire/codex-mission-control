"""Password-encrypted, non-executable portable summaries. Never a queue restore.

DPAPI remains the protection for local state. Archives use authenticated AES-GCM
so another Windows profile can import explicitly chosen, sanitized summaries.
Passwords are never persisted. Python cannot guarantee erasure of string copies.
"""
import hashlib
import json
import math
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import safety
from .secure_files import read_file, write_file
from .state import StateError

MAGIC = b'CMCPORT1'
MAX_PAYLOAD = 8 * 1024 * 1024
MAX_ARCHIVE = MAX_PAYLOAD + 52
MAX_RECORDS = 2000
ITERATIONS = 600_000
PREFERENCE_ENUMS = {'language': {'ru', 'en'}, 'theme': {'dark', 'light'}, 'mode': {'economy', 'balanced', 'quality'},
                    'policy': {'balanced', 'weekly', 'reserve', 'stop'}}
PREFERENCE_BOOLS = {'closeToTray', 'notifications', 'reducedMotion', 'overlayCompact', 'overlayPinned', 'overlayCodexOnly'}


def _password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 1024:
        raise StateError('Пароль архива должен содержать от 12 до 1024 символов.')
    return value.encode('utf-8')


def _text(value, limit=2048):
    if not isinstance(value, str) or len(value) > limit:
        raise StateError('Некорректные или слишком длинные данные архива.')
    return safety.redact(value)


def _summary(preferences, projects, history):
    if not isinstance(preferences, dict):
        raise StateError('Некорректные настройки архива.')
    clean = {}
    if 'creditPolicy' in preferences:
        from dataclasses import asdict
        from .credit_policy import CreditPolicy
        try:clean['creditPolicy'] = asdict(CreditPolicy(**preferences['creditPolicy']))
        except (ValueError,TypeError) as error:raise StateError('Invalid portable credit policy') from error
    if 'modelPolicies' in preferences:
        from .model_policy import validate_policy
        try:clean['modelPolicies'] = validate_policy(preferences['modelPolicies'])
        except ValueError as error:raise StateError('Invalid portable model policy') from error
    for key, options in PREFERENCE_ENUMS.items():
        if key in preferences:
            value = preferences[key]
            if not isinstance(value, str) or value not in options:
                raise StateError('Некорректная настройка архива.')
            clean[key] = value
    for key in PREFERENCE_BOOLS:
        if key in preferences:
            if type(preferences[key]) is not bool:
                raise StateError('Некорректная настройка архива.')
            clean[key] = preferences[key]
    if 'maxAttempts' in preferences:
        value = preferences['maxAttempts']
        if type(value) is not int or not 1 <= value <= 8:
            raise StateError('Некорректное число попыток архива.')
        clean['maxAttempts'] = value
    clean.update(codex='codex', setupComplete=False, resumeOnLaunch=False)
    for collection in (projects, history):
        if not isinstance(collection, list) or len(collection) > MAX_RECORDS:
            raise StateError('Архив содержит слишком много записей.')
    names = []
    for project in projects:
        if not isinstance(project, dict):
            raise StateError('Некорректный проект архива.')
        names.append({key: _text(project[key]) for key in ('name', 'path') if key in project})
    records = []
    for record in history:
        if not isinstance(record, dict):
            raise StateError('Некорректная история архива.')
        item = {key: _text(record[key]) for key in ('title', 'status', 'model', 'effort') if key in record and record[key] is not None}
        for key in ('duration', 'attempts', 'completedAt', 'createdAt'):
            if key in record and record[key] is not None:
                value = record[key]
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e15:
                    raise StateError('Некорректная статистика архива.')
                item[key] = value
        records.append(item)
    return {'version': 1, 'preferences': clean, 'projects': names, 'history': records}


def export_archive(path, passphrase, *, preferences, projects, history):
    password = _password(passphrase)
    data = _summary(preferences, projects, history)
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(raw) > MAX_PAYLOAD:
        raise StateError('Архив превышает допустимый размер.')
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = MAGIC + salt + nonce
    key = hashlib.pbkdf2_hmac('sha256', password, salt, ITERATIONS, dklen=32)
    encrypted = AESGCM(key).encrypt(nonce, raw, header)
    write_file(path, header + encrypted, new=True)
    return {'projectCount': len(data['projects']), 'historyCount': len(data['history'])}


def import_archive(path, passphrase):
    password = _password(passphrase)
    raw = read_file(path, limit=MAX_ARCHIVE)
    if raw is None or len(raw) < 52 or raw[:8] != MAGIC:
        raise StateError('Неизвестный или повреждённый архив.')
    header, salt, nonce = raw[:36], raw[8:24], raw[24:36]
    key = hashlib.pbkdf2_hmac('sha256', password, salt, ITERATIONS, dklen=32)
    try:
        plaintext = AESGCM(key).decrypt(nonce, raw[36:], header)
        if len(plaintext) > MAX_PAYLOAD:
            raise StateError('Архив превышает допустимый размер.')
        data = json.loads(plaintext)
    except (InvalidTag, ValueError, UnicodeError, RecursionError):
        raise StateError('Неверный пароль или повреждённый архив.') from None
    if (not isinstance(data, dict) or set(data) != {'version', 'preferences', 'projects', 'history'}
            or type(data['version']) is not int or data['version'] != 1):
        raise StateError('Неизвестная версия или структура архива.')
    result = _summary(data['preferences'], data['projects'], data['history'])
    result['trusted'] = False
    return result
