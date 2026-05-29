' Silent launcher for the Razer Keylight controller.
' Resolves its OWN folder (not the caller's working directory) so it launches
' correctly no matter how it's started: Startup shortcut, double-click, etc.
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
' 0 = hidden window, False = don't wait. pythonw.exe = no console.
WshShell.Run "pythonw.exe """ & scriptDir & "\main.pyw""", 0, False
