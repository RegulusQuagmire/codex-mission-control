Option Explicit
Dim fso, shell, root, python, script
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
python = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")
script = fso.BuildPath(root, "Mission Control.pyw")
If Not fso.FileExists(python) Then
    MsgBox "Project Python environment is missing. See docs/DESKTOP.md.", 48, "Mission Control"
    WScript.Quit 1
End If
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & script & Chr(34), 0, False
