' Stop ChaosTutor.vbs
'
' Double-click this to stop the backend/frontend/AI-tutor processes started
' by "Start ChaosTutor.vbs". Since those run with no visible window, this
' is the normal way to shut them down (closing a browser tab does not).

Option Explicit

Dim fso, shell, root, logsDir, pidFile, pidStream, line, killedAny

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
logsDir = root & "\logs"
pidFile = logsDir & "\running_pids.txt"
killedAny = False

If fso.FileExists(pidFile) Then
    Set pidStream = fso.OpenTextFile(pidFile, 1) ' 1 = ForReading
    Do While Not pidStream.AtEndOfStream
        line = Trim(pidStream.ReadLine)
        If line <> "" Then
            shell.Run "taskkill /PID " & line & " /T /F", 0, True
            killedAny = True
        End If
    Loop
    pidStream.Close
    fso.DeleteFile(pidFile)
End If

' Ensure standard Chaos Tutor ports are always freed
KillPortListener 8090
KillPortListener 5173
KillPortListener 5000

Dim showMsg
showMsg = True
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "/nomsg" Or LCase(WScript.Arguments(0)) = "-nomsg" Then
        showMsg = False
    End If
End If

If showMsg Then
    If killedAny Then
        MsgBox "Chaos Tutor stopped.", 64, "Chaos Tutor"
    Else
        MsgBox "Chaos Tutor doesn't look like it's running (no logs\running_pids.txt found).", 48, "Chaos Tutor"
    End If
End If

Sub KillPortListener(port)
    On Error Resume Next
    Dim execObj, outLine, parts, pidVal
    Set execObj = shell.Exec("cmd /c netstat -ano | findstr :" & port)
    Do While Not execObj.StdOut.AtEndOfStream
        outLine = Trim(execObj.StdOut.ReadLine)
        If InStr(outLine, "LISTENING") > 0 Then
            parts = Split(outLine)
            pidVal = Trim(parts(UBound(parts)))
            If IsNumeric(pidVal) And CLng(pidVal) > 0 Then
                shell.Run "taskkill /PID " & pidVal & " /T /F", 0, True
                killedAny = True
            End If
        End If
    Loop
End Sub
