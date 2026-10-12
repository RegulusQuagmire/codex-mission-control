"""Semantic Qt theme for the selected Mission Control direction."""
import os
from pathlib import Path
from PySide6.QtGui import QFont,QFontDatabase,QPalette,QColor

TOKENS={
 'dark':dict(bg='#09151c',surface='#122932',raised='#1d3d47',border='#38616c',text='#effbff',muted='#acc8d0',accent='#7de0d2',warning='#edc88e'),
 'light':dict(bg='#edf5f5',surface='#ffffff',raised='#dfedee',border='#8faeb5',text='#142f38',muted='#46616c',accent='#006b65',warning='#80510c')}


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
        QLabel#title {{ font-size:27px; font-weight:600; }}
        QLabel#missionTitle {{ font-size:23px; font-weight:600; }}
        QLabel#section {{ font-size:17px; font-weight:600; }}
        QLabel#muted {{ color:{p['muted']}; }}
        QLabel#accent {{ color:{p['accent']}; }}
        QLabel#warning {{ color:{p['warning']}; }}
        QFrame#surface {{ background:{p['surface']}; border:1px solid {p['border']}; border-radius:16px; }}
        QFrame#inset {{ background:{p['bg']}; border:1px solid {p['border']}; border-radius:10px; }}
        QPushButton {{ background:{p['raised']}; border:1px solid {p['border']}; border-radius:8px; padding:7px 12px; min-height:20px; }}
        QPushButton:hover {{ border-color:{p['accent']}; }}
        QPushButton:focus,QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus {{ border:2px solid {p['accent']}; }}
        QPushButton:disabled {{ color:{p['muted']}; background:{p['surface']}; }}
        QPushButton#primary {{ background:{p['accent']}; color:{p['bg']}; font-weight:600; }}
        QPushButton#primary:disabled {{ background:{p['surface']}; color:{p['muted']}; }}
        QLineEdit,QPlainTextEdit,QComboBox,QSpinBox {{ background:{p['surface']}; border:1px solid {p['border']}; border-radius:7px; padding:7px; selection-background-color:{p['accent']}; selection-color:{p['bg']}; }}
        QPlainTextEdit {{ font-family:Consolas; font-size:13px; }}
        QTableWidget,QListWidget {{ background:{p['surface']}; border:1px solid {p['border']}; border-radius:9px; alternate-background-color:{p['raised']}; selection-background-color:{p['raised']}; selection-color:{p['text']}; }}
        QHeaderView::section {{ background:{p['raised']}; padding:9px; border:0; color:{p['muted']}; }}
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
        QCheckBox::indicator {{ width:16px; height:16px; }}
    ''')
