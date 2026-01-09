Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw.exe """ & WshShell.CurrentDirectory & "\main.pyw""", 0, False