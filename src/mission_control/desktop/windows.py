"""Small Win32 integration: hotkey messages and foreground process identity only.

No injection, input hooks, screen capture, window-title collection or telemetry.
API contracts: Microsoft Learn RegisterHotKey, SetWinEventHook (OUTOFCONTEXT),
QueryFullProcessImageNameW. Foreground identification is a UI convenience, not trust.
"""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import PureWindowsPath
from PySide6.QtCore import QObject,Signal,QAbstractNativeEventFilter


def parse_hotkey(text):
    parts=[p.strip().upper() for p in text.split('+')]
    modifiers={'CTRL':2,'SHIFT':4,'ALT':1}
    if len(parts)<2 or len(parts)!=len(set(parts)) or any(p not in modifiers for p in parts[:-1]):
        raise ValueError('Используйте Ctrl/Shift/Alt и букву, цифру или F1–F11')
    key=parts[-1]
    if len(key)==1 and key.isascii() and key.isalnum():vk=ord(key)
    elif key.startswith('F') and key[1:].isdigit() and 1<=int(key[1:])<=11:vk=0x70+int(key[1:])-1
    else:raise ValueError('Недопустимая клавиша')
    return sum(modifiers[p] for p in parts[:-1])|0x4000,vk


def codex_image(path):
    path=PureWindowsPath(path)
    if path.name.casefold()!='codex.exe':return False
    local=PureWindowsPath(os.environ.get('LOCALAPPDATA','C:/not-configured'))/'OpenAI'/'Codex'
    packages=PureWindowsPath(os.environ.get('ProgramFiles','C:/Program Files'))/'WindowsApps'
    return path.is_relative_to(local) or (path.is_relative_to(packages) and any(p.casefold().startswith('openai.codex_') for p in path.parts))


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self,owner):super().__init__();self.owner=owner
    def nativeEventFilter(self,event_type,message):
        if os.name=='nt':
            msg=w.MSG.from_address(int(message))
            if msg.message==0x0312 and msg.wParam==self.owner.identity:
                self.owner.activated.emit();return True,0
        return False,0


class WindowsIntegration(QObject):
    activated=Signal()
    foreground_changed=Signal(bool)
    warning=Signal(str)
    def __init__(self,app):
        super().__init__();self.app=app;self.identity=0x4d43;self.registered=False;self.text=None
        self._requested=None
        self.hook=None;self._callback=None;self.filter=_HotkeyFilter(self);self.monitoring=False
        if os.name!='nt':return
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.user.RegisterHotKey.argtypes=[w.HWND,ctypes.c_int,w.UINT,w.UINT];self.user.RegisterHotKey.restype=w.BOOL
        self.user.UnregisterHotKey.argtypes=[w.HWND,ctypes.c_int];self.user.UnregisterHotKey.restype=w.BOOL
        self.user.GetForegroundWindow.argtypes=[];self.user.GetForegroundWindow.restype=w.HWND
        self.user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)];self.user.GetWindowThreadProcessId.restype=w.DWORD
        self.kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.kernel.OpenProcess.restype=w.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)];self.kernel.QueryFullProcessImageNameW.restype=w.BOOL
        self.kernel.CloseHandle.argtypes=[w.HANDLE];self.kernel.CloseHandle.restype=w.BOOL
        self.app.installNativeEventFilter(self.filter)
    def set_hotkey(self,text):
        if text==self._requested:return self.registered
        self._requested=text
        if not text:
            if self.registered:self.user.UnregisterHotKey(None,self.identity)
            self.registered=False;self.text='';return True
        try:modifiers,key=parse_hotkey(text)
        except ValueError as error:self.warning.emit(str(error));return False
        if os.name!='nt':self.warning.emit('Глобальные сочетания доступны в Windows');return False
        candidate=0x4d44 if self.identity==0x4d43 else 0x4d43
        if not self.user.RegisterHotKey(None,candidate,modifiers,key):
            self.warning.emit('Сочетание занято или недоступно. Выберите другое в настройках.');return False
        if self.registered:self.user.UnregisterHotKey(None,self.identity)
        self.identity=candidate;self.registered=True;self.text=text;return True
    def set_monitoring(self,enabled):
        if os.name!='nt':return
        if self.monitoring==enabled:return
        self.monitoring=enabled
        if not enabled:
            if self.hook:self.user.UnhookWinEvent(self.hook);self.hook=None
            return
        callback_type=ctypes.WINFUNCTYPE(None,w.HANDLE,w.DWORD,w.HWND,w.LONG,w.LONG,w.DWORD,w.DWORD)
        def changed(*_):self.foreground_changed.emit(self.is_codex_foreground())
        self._callback=callback_type(changed)
        self.user.SetWinEventHook.argtypes=[w.DWORD,w.DWORD,w.HMODULE,callback_type,w.DWORD,w.DWORD,w.DWORD]
        self.user.SetWinEventHook.restype=w.HANDLE
        self.user.UnhookWinEvent.argtypes=[w.HANDLE];self.user.UnhookWinEvent.restype=w.BOOL
        self.hook=self.user.SetWinEventHook(3,3,None,self._callback,0,0,0)  # EVENT_SYSTEM_FOREGROUND, OUTOFCONTEXT
        if not self.hook:
            self.monitoring=False;self.warning.emit('Определение окна Codex недоступно. Используйте ручной показ оверлея.')
        self.foreground_changed.emit(self.is_codex_foreground())
    def is_codex_foreground(self):
        if os.name!='nt':return False
        hwnd=self.user.GetForegroundWindow();pid=w.DWORD()
        if not hwnd:return False
        self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        handle=self.kernel.OpenProcess(0x1000,False,pid.value)
        if not handle:return False
        try:
            buffer=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(buffer))
            return bool(self.kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)) and codex_image(buffer.value))
        finally:self.kernel.CloseHandle(handle)
    def close(self):
        if os.name=='nt':
            self.set_monitoring(False)
            if self.registered:self.user.UnregisterHotKey(None,self.identity)
            self.app.removeNativeEventFilter(self.filter)
        self.registered=False
