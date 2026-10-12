"""Small Qt bindings: retranslate text without rebuilding widgets or touching data.

Native signals, IDs, selections and user edits are preserved. Only LocalizedText
values are retained as bindings; plain strings remain opaque user/technical data.
"""
from PySide6 import QtWidgets as W, QtGui as G
from PySide6.QtCore import QObject, QSignalBlocker
from .i18n import manager, LocalizedText


class TextBindings(QObject):
    def __init__(self, widget):
        super().__init__(widget); self.widget = widget; self.values = {}
        manager.changed.connect(self.refresh)
    def set(self, method, value, prefix=()):
        key = (method, prefix)
        if isinstance(value, LocalizedText): self.values[key] = value
        else: self.values.pop(key, None)
        getattr(self.widget, method)(*prefix, str(value))
    def refresh(self, *_):
        with QSignalBlocker(self.widget):
            for (method, prefix), value in tuple(self.values.items()):
                bar = self.widget.verticalScrollBar() if method == 'setPlainText' else None
                position = bar.value() if bar else None
                getattr(self.widget, method)(*prefix, str(value))
                if bar: bar.setValue(position)


def set_text(widget, method, value, *prefix):
    bindings = getattr(widget, '_text_bindings', None)
    if bindings is None:
        bindings = widget._text_bindings = TextBindings(widget)
    bindings.set(method, value, prefix)


class Common:
    def _language_updated(self, *_): self.update()
    def setWindowTitle(self, value): set_text(self, '_native_title', value)
    def _native_title(self, value): super().setWindowTitle(value)
    def setToolTip(self, value): set_text(self, '_native_tip', value)
    def _native_tip(self, value): super().setToolTip(value)
    def setAccessibleName(self, value): set_text(self, '_native_access', value)
    def _native_access(self, value): super().setAccessibleName(value)


def textual(name, methods=()):
    native = getattr(W, name, None) or getattr(G, name)
    attrs = {}
    for method in methods:
        def setter(self, value, _method=method): set_text(self, '_native_' + _method, value)
        def original(self, value, _method=method): getattr(native, _method)(self, value)
        attrs[method] = setter; attrs['_native_' + method] = original
    def init(self, *args, **kwargs):
        saved = args[0] if args and isinstance(args[0], LocalizedText) else None
        native.__init__(self, *(str(a) if isinstance(a, LocalizedText) else a for a in args), **kwargs)
        if hasattr(self, 'update'): manager.changed.connect(self._language_updated)
        if saved is not None and 'setText' in methods: self.setText(saved)
    attrs['__init__'] = init
    return type(name, (Common, native), attrs)


QLabel = textual('QLabel', ('setText',))
QPushButton = textual('QPushButton', ('setText',))
_CheckBox = textual('QCheckBox', ('setText',))


class QCheckBox(_CheckBox):
    """Native checkbox state/input, with a wrapped caption for long consent text."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        policy=W.QSizePolicy(W.QSizePolicy.Preferred,W.QSizePolicy.Preferred)
        policy.setHeightForWidth(True); self.setSizePolicy(policy)
    def heightForWidth(self, width):
        from PySide6.QtCore import Qt, QRect
        return max(24,self.fontMetrics().boundingRect(QRect(0,0,max(30,width-30),10000),Qt.TextWordWrap,self.text()).height()+6)
    def sizeHint(self):
        from PySide6.QtCore import QSize
        width=min(460,super().sizeHint().width()); return QSize(width,self.heightForWidth(width))
    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(140,24)
    def hitButton(self, point): return self.rect().contains(point)
    def paintEvent(self, event):
        from PySide6.QtCore import Qt, QRect
        from PySide6.QtGui import QPainter, QPalette
        option=W.QStyleOptionButton();self.initStyleOption(option);option.text=''
        painter=QPainter(self);self.style().drawControl(W.QStyle.CE_CheckBox,option,painter,self)
        group=QPalette.Active if self.isEnabled() else QPalette.Disabled
        painter.setPen(self.palette().color(group,QPalette.WindowText))
        painter.drawText(QRect(28,0,max(0,self.width()-28),self.height()),Qt.AlignVCenter|Qt.TextWordWrap,self.text())
QLineEdit = textual('QLineEdit', ('setPlaceholderText',))
QPlainTextEdit = textual('QPlainTextEdit', ('setPlaceholderText', 'setPlainText'))
QSpinBox = textual('QSpinBox', ('setSuffix',))
QWidget = textual('QWidget')
QDialog = textual('QDialog')
QMainWindow = textual('QMainWindow')
QAction = textual('QAction', ('setText',))


class QMenu(Common, W.QMenu):
    def addAction(self, text, callback=None):
        if isinstance(text, LocalizedText):
            action = QAction(text, self)
            if callback is not None: action.triggered.connect(callback)
            super().addAction(action); return action
        return super().addAction(text) if callback is None else super().addAction(text, callback)


class QComboBox(Common, W.QComboBox):
    def addEnums(self, values):
        from .i18n import enum_label
        for value in values: self.addItem(enum_label(value), value)
    def selectData(self, value): self.setCurrentIndex(max(0, self.findData(value)))
    def addItem(self, text, userData=None):
        index = self.count(); super().addItem(str(text), userData)
        set_text(self, 'setItemText', text, index)
    def addItems(self, texts):
        for text in texts: self.addItem(text)
    def clear(self):
        if hasattr(self, '_text_bindings'):
            self._text_bindings.values={key:value for key,value in self._text_bindings.values.items() if key[0]!='setItemText'}
        super().clear()


class QListWidget(Common, W.QListWidget):
    def addItem(self, value):
        if isinstance(value, LocalizedText):
            item = QListWidgetItem(value); super().addItem(item)
        else: super().addItem(value)
    def addItems(self, values):
        for value in values: self.addItem(value)
    def __init__(self, *args):
        super().__init__(*args); manager.changed.connect(self._translate_items)
    def _translate_items(self, *_):
        for index in range(self.count()):
            item = self.item(index)
            if hasattr(item, '_localized_text'): item.setText(str(item._localized_text))


class QListWidgetItem(W.QListWidgetItem):
    def __init__(self, text='', *args):
        super().__init__(str(text), *args)
        if isinstance(text, LocalizedText): self._localized_text = text


class QTableWidgetItem(W.QTableWidgetItem):
    def __init__(self, text='', *args):
        super().__init__(str(text), *args)
        if isinstance(text, LocalizedText): self._localized_text = text


class QTableWidget(Common, W.QTableWidget):
    def __init__(self, *args):
        super().__init__(*args); manager.changed.connect(self._translate_items)
    def setHorizontalHeaderLabels(self, values):
        self._header_labels = values; super().setHorizontalHeaderLabels([str(x) for x in values])
    def _translate_items(self, *_):
        if hasattr(self, '_header_labels'): self.setHorizontalHeaderLabels(self._header_labels)
        for row in range(self.rowCount()):
            for col in range(self.columnCount()):
                item = self.item(row,col)
                if item and hasattr(item, '_localized_text'): item.setText(str(item._localized_text))


class QFormLayout(W.QFormLayout):
    def addRow(self, *args):
        if args and isinstance(args[0], LocalizedText): args = (QLabel(args[0]), *args[1:])
        super().addRow(*args)


class QTabWidget(Common, W.QTabWidget):
    def addTab(self, widget, title):
        index = super().addTab(widget, str(title)); set_text(self, 'setTabText', title, index); return index


class QWizard(Common, W.QWizard):
    def setButtonText(self, which, text): set_text(self, '_native_button', text, which)
    def _native_button(self, which, text): super().setButtonText(which, text)


class QWizardPage(Common, W.QWizardPage):
    def setTitle(self, value): set_text(self, '_native_title_text', value)
    def _native_title_text(self, value): super().setTitle(value)


class QFileDialog:
    """Use native file dialogs; translate only developer captions and filters."""
    @staticmethod
    def _call(name, *args, **kwargs):
        return getattr(W.QFileDialog, name)(*(str(x) if isinstance(x, LocalizedText) else x for x in args), **kwargs)
    getOpenFileName = staticmethod(lambda *a, **k: QFileDialog._call('getOpenFileName', *a, **k))
    getOpenFileNames = staticmethod(lambda *a, **k: QFileDialog._call('getOpenFileNames', *a, **k))
    getSaveFileName = staticmethod(lambda *a, **k: QFileDialog._call('getSaveFileName', *a, **k))
    getExistingDirectory = staticmethod(lambda *a, **k: QFileDialog._call('getExistingDirectory', *a, **k))


class QMessageBox(W.QMessageBox):
    @staticmethod
    def _call(kind, parent, title, text, buttons=None, defaultButton=W.QMessageBox.NoButton):
        from .i18n import tr
        default = W.QMessageBox.Yes | W.QMessageBox.No if kind == 'question' else W.QMessageBox.Ok
        box = W.QMessageBox(parent); box.setWindowTitle(str(title)); box.setText(str(text))
        box.setIcon({'question':W.QMessageBox.Question,'warning':W.QMessageBox.Warning,'information':W.QMessageBox.Information}[kind])
        box.setTextFormat(__import__('PySide6.QtCore', fromlist=['Qt']).Qt.PlainText)
        box.setStandardButtons(default if buttons is None else buttons); box.setDefaultButton(defaultButton)
        for button, key in ((W.QMessageBox.Yes,'Да'),(W.QMessageBox.No,'Нет'),(W.QMessageBox.Ok,'ОК'),(W.QMessageBox.Cancel,'Отмена')):
            if box.button(button): box.button(button).setText(str(tr(key)))
        box.exec(); return box.standardButton(box.clickedButton())
    question = staticmethod(lambda *a, **k: QMessageBox._call('question', *a, **k))
    information = staticmethod(lambda *a, **k: QMessageBox._call('information', *a, **k))
    warning = staticmethod(lambda *a, **k: QMessageBox._call('warning', *a, **k))
