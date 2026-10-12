"""Presentation-only RU/EN catalog and Qt language-change signal.

Only explicit tr() calls translate developer-owned text. User data, protocol
values and persistence never pass through an implicit text replacement filter.
"""
import json
import re
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QTranslator, QLibraryInfo, QCoreApplication

CATALOG = json.loads(Path(__file__).with_name('translations.json').read_text(encoding='utf-8'))


class LanguageManager(QObject):
    changed = Signal(str)
    def __init__(self):
        super().__init__(); self.language = 'ru'
        self.qt_translator=None;self.qt_language=None


manager = LanguageManager()


def language():
    return manager.language


def set_language(value):
    if value not in ('ru', 'en'): raise ValueError('Unsupported UI language')
    app=QCoreApplication.instance()
    if app and manager.qt_language!=value:
        if manager.qt_translator:
            app.removeTranslator(manager.qt_translator);manager.qt_translator.deleteLater()
        manager.qt_translator=None
        if value=='ru':
            translator=QTranslator(manager)
            if translator.load('qtbase_ru',QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
                manager.qt_translator=translator;app.installTranslator(translator)
        manager.qt_language=value
    if value != manager.language:
        manager.language = value
        manager.changed.emit(value)


class LocalizedText:
    """A renderable expression retaining literal translations and opaque values."""
    def __init__(self, render): self.render = render
    def __str__(self): return self.render()
    def __bool__(self): return bool(str(self))
    def __len__(self): return len(str(self))
    def __contains__(self, value): return str(value) in str(self)
    def __getitem__(self, item): return LocalizedText(lambda: str(self)[item])
    def __eq__(self, other): return str(self) == str(other)
    def __add__(self, other): return LocalizedText(lambda: str(self) + str(other))
    def __radd__(self, other): return LocalizedText(lambda: str(other) + str(self))
    def __format__(self, spec): return format(str(self), spec)
    def __getattr__(self, name): return getattr(str(self), name)


def tr(source, **values):
    def render():
        entry = CATALOG.get(source)
        text = entry.get(language()) or entry['ru'] if entry else '[' + source + ']'
        return text.format(**{key: str(value) if isinstance(value, LocalizedText) else value for key,value in values.items()}) if values else text
    return LocalizedText(render)


def display(value):
    return value if isinstance(value, LocalizedText) else str(value)


def join_text(separator, values):
    items = tuple(values)
    if not any(isinstance(x, LocalizedText) for x in items): return str(separator).join(items)
    return LocalizedText(lambda: str(separator).join(str(x) for x in items))


def format_text(parts):
    return LocalizedText(lambda: ''.join(str(x) for x in parts))


def format_value(value, conversion=-1, spec=''):
    def render():
        item = str(value) if isinstance(value, LocalizedText) else value
        if conversion == 114: item = repr(item)
        elif conversion == 115: item = str(item)
        elif conversion == 97: item = ascii(item)
        return format(item, str(spec))
    return LocalizedText(render)


def enum_label(value):
    return tr({'dark':'Тёмная','light':'Светлая','economy':'Экономичная',
               'balanced':'Сбалансированная','quality':'Качественная','manual':'Вручную',
               'weekly':'Недельный резерв','reserve':'Резерв обоих окон','stop':'Ожидание при исчерпании',
               'minimal':'Минимальный','low':'Низкий','medium':'Средний','high':'Высокий',
               'xhigh':'Очень высокий','max':'Максимальный','ultra':'Предельный','critical':'Критический'}.get(value, value)) if value in {
               'dark','light','economy','balanced','quality','manual','weekly','reserve','stop',
               'minimal','low','medium','high','xhigh','max','ultra','critical'} else value


def message_text(value):
    """Translate known controller diagnostics, never model output or user input."""
    if isinstance(value, LocalizedText): return value
    source = str(value)
    if source in CATALOG: return tr(source)
    for prefix in ('Required file content missing: ', 'Required file content missing after checks: '):
        if source.startswith(prefix):return tr(prefix)+source[len(prefix):]
    for prefix in ('Рабочая папка: ', 'Настройка не сохранена: '):
        if source.startswith(prefix):return tr(prefix)+message_text(source[len(prefix):])
    # The router composes these exact developer-owned segments. Model IDs and
    # counts are opaque parameters; no substitution is applied to user content.
    if re.match(r'^(LOW|MEDIUM|HIGH|CRITICAL): chose ',source) and '; ' in source:
        return join_text('; ',(message_text(part) for part in source.split('; ')))
    choice=re.fullmatch(r'(LOW|MEDIUM|HIGH|CRITICAL): chose (\S+) / (\w+) \((economy|balanced|quality|manual)\)',source)
    if choice:
        level,model,effort,mode=choice.groups()
        return tr('Выбор модели: {model} / {effort} · {mode} · сложность {level}',model=model,
                  effort=enum_label(effort),mode=enum_label(mode),level=enum_label(level.lower()))
    patterns=(
        (r'observed validated outcomes=(\d+) success/(\d+) failure','Проверенные результаты: {v0} успешно / {v1} с ошибкой'),
        (r'estimated files=(\d+)','Оценка числа файлов: {v0}'),
        (r'previous errors=(\d+)','Предыдущих ошибок: {v0}'),
        (r'risk=(low|medium|high|critical)','Риск: {v0}'),
        (r'validation failed: raise effort to (\w+)','Проверка не пройдена: повысить уровень рассуждения до {v0}'),
        (r'validation failed: switch to stronger profile (\S+)','Проверка не пройдена: перейти на более сильный профиль {v0}'),
    )
    for pattern,key in patterns:
        match=re.fullmatch(pattern,source)
        if match:return tr(key,**{f'v{i}':enum_label(v) for i,v in enumerate(match.groups())})
    return LocalizedText(lambda: source)
