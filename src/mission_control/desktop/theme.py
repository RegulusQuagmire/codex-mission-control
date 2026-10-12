"""Semantic Qt theme for the selected Mission Control direction."""
import os
from pathlib import Path
from PySide6.QtGui import QFont,QFontDatabase,QPalette,QColor

TOKENS={
 'dark':dict(bg='#0c121b',surface='#141f2b',raised='#1f2e3c',border='#63798d',line='#2b3c4c',text='#e9f0f6',muted='#a8b9c9',accent='#77ddcb',warning='#f1c579',danger='#ffa7a3',success='#99dbaf'),
 'light':dict(bg='#f3f6fa',surface='#ffffff',raised='#e8eef4',border='#76879a',line='#d3dee8',text='#172b3e',muted='#4f6376',accent='#006c65',warning='#80500a',danger='#a92836',success='#236735')}

# Project-specific Fluent-inspired aliases, not a verbatim upstream token snapshot.
METRICS=dict(space_small=8,space_medium=16,space_large=24,radius_control=6,radius_surface=10,
             body=14,caption=12,section=18,title=30,motion_fast=160,motion_normal=220)


def tokens():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance()
    return TOKENS['light' if app and app.property('mcTheme')=='light' else 'dark']


def apply_theme(app,theme='dark'):
    if not QFontDatabase.families() and os.name=='nt':
        directory=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        for name in ('segoeui.ttf','segoeuib.ttf','consola.ttf'):QFontDatabase.addApplicationFont(str(directory/name))
    theme='light' if theme=='light' else 'dark';app.setProperty('mcTheme',theme)
    p=TOKENS[theme];app.setFont(QFont('Segoe UI',10));palette=QPalette()
    for role,key in ((QPalette.Window,'bg'),(QPalette.WindowText,'text'),(QPalette.Base,'surface'),(QPalette.Text,'text'),
        (QPalette.Button,'raised'),(QPalette.ButtonText,'text'),(QPalette.Highlight,'accent'),(QPalette.HighlightedText,'bg')):
        palette.setColor(role,QColor(p[key]))
    palette.setColor(QPalette.Disabled,QPalette.Text,QColor(p['muted']))
    palette.setColor(QPalette.Disabled,QPalette.ButtonText,QColor(p['muted']));app.setPalette(palette)
    app.setStyleSheet(f'''
        QWidget {{ color:{p['text']}; font-family:"Segoe UI"; font-size:14px; }}
        QMainWindow,QDialog,QWizard {{ background:{p['bg']}; }}
        QLabel {{ background:transparent; }}
        QLabel#title {{ font-size:30px; font-weight:600; }}
        QLabel#missionTitle {{ font-size:26px; font-weight:600; }}
        QLabel#metric {{ font-size:28px; font-weight:600; }}
        QLabel#section {{ font-size:17px; font-weight:600; }}
        QLabel#muted {{ color:{p['muted']}; }}
        QLabel#accent {{ color:{p['accent']}; }}
        QLabel#warning {{ color:{p['warning']}; }}
        QLabel[fluentSeverity="warning"] {{ color:{p['warning']}; }}
        QLabel[fluentSeverity="danger"] {{ color:{p['danger']}; }}
        QFrame#surface {{ background:{p['surface']}; border:1px solid {p['line']}; border-radius:10px; }}
        QFrame[fluentRole="metricStrip"] {{ background:{p['surface']}; border:1px solid {p['line']}; border-radius:10px; }}
        QFrame[fluentRole="messageBar"] {{ background:{p['surface']}; border:1px solid {p['line']}; border-left:3px solid {p['accent']}; border-radius:8px; }}
        QFrame[fluentRole="messageBar"][fluentSeverity="warning"] {{ border-left-color:{p['warning']}; }}
        QFrame[fluentRole="messageBar"][fluentSeverity="danger"] {{ border-left-color:{p['danger']}; }}
        QFrame[fluentRole="messageBar"][fluentSeverity="success"] {{ border-left-color:{p['success']}; }}
        QFrame#inset {{ background:{p['bg']}; border:1px solid {p['border']}; border-radius:10px; }}
        QPushButton {{ background:{p['raised']}; border:2px solid {p['line']}; border-radius:6px; padding:6px 12px; min-height:22px; }}
        QPushButton:hover {{ border-color:{p['accent']}; }}
        QPushButton:pressed,QPushButton:checked {{ background:{p['surface']}; border-color:{p['accent']}; }}
        QPushButton[fluentAppearance="danger"] {{ color:{p['danger']}; }}
        QPushButton:focus,QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus {{ border:2px solid {p['accent']}; }}
        QPushButton:disabled {{ color:{p['muted']}; background:{p['surface']}; }}
        QPushButton#primary {{ background:{p['accent']}; color:{p['bg']}; font-weight:600; }}
        QPushButton#primary:disabled {{ background:{p['surface']}; color:{p['muted']}; }}
        QLineEdit,QPlainTextEdit,QComboBox,QSpinBox {{ background:{p['surface']}; border:2px solid {p['border']}; border-radius:6px; padding:6px; selection-background-color:{p['accent']}; selection-color:{p['bg']}; }}
        QSpinBox:focus {{ border-color:{p['accent']}; }}
        QPlainTextEdit {{ font-size:14px; }}
        QPlainTextEdit#code {{ font-family:Consolas; }}
        QTableWidget,QListWidget {{ background:{p['surface']}; border:1px solid {p['border']}; border-radius:9px; alternate-background-color:{p['raised']}; selection-background-color:{p['raised']}; selection-color:{p['text']}; }}
        QHeaderView::section {{ background:{p['raised']}; padding:10px; border:0; color:{p['muted']}; }}
        QTableWidget {{ gridline-color:{p['line']}; }}
        QTableWidget::item:selected {{ background:{p['raised']}; color:{p['accent']}; }}
        QTableWidget::item:focus,QListWidget::item:focus {{ border:1px solid {p['accent']}; }}
        QListWidget::item:hover {{ background:{p['raised']}; }}
        QTableWidget::item {{ padding:7px; }}
        QListWidget::item {{ padding:8px 10px; margin:2px; border-radius:7px; }}
        QListWidget::item:selected {{ background:{p['raised']}; color:{p['accent']}; }}
        QListWidget#navigation {{ background:transparent; border:0; }}
        QTabBar::tab {{ background:{p['surface']}; padding:10px; }}
        QTabBar::tab:selected {{ color:{p['accent']}; }}
        QToolTip,QMenu {{ background:{p['surface']}; color:{p['text']}; border:1px solid {p['border']}; }}
        QMenu::item {{ padding:8px 20px; }}
        QMenu::item:selected {{ background:{p['raised']}; }}
        QScrollArea,QStackedWidget {{ background:transparent; border:0; }}
        QScrollBar:vertical {{ background:transparent; width:8px; margin:0; }}
        QScrollBar::handle:vertical {{ background:{p['border']}; border-radius:4px; min-height:24px; }}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}
        QCheckBox {{ spacing:8px; background:transparent; }}
        QCheckBox::indicator {{ width:16px; height:16px; border:1px solid {p['border']}; border-radius:3px; background:{p['surface']}; }}
        QCheckBox::indicator:checked {{ background:{p['accent']}; border-color:{p['accent']}; }}
        QCheckBox:focus {{ outline:1px solid {p['accent']}; }}
    ''')
