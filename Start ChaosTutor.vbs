' Start ChaosTutor.vbs
'
' Double-click this file to start CD-SET / Chaos Tutor on Windows.
'   - No console/terminal window is ever shown.
'   - No Administrator prompt.
'   - Opens your browser to the app once the services have had time to start.
'
' Output from each service is written to the "logs" folder next to this
' file (backend.log, frontend.log, ai_tutor.log) so you can check what
' happened if something doesn't come up. Process IDs are recorded in
' logs\running_pids.txt so "Stop ChaosTutor.vbs" can shut everything down
' cleanly.
'
' Note: network-level sandbox isolation (blocking a submitted project from
' reaching the internet during a chaos run) requires the backend to run as
' Administrator. This launcher deliberately does NOT elevate, so the app
' runs in its default "degraded" sandbox mode (still workspace-isolated,
' still fixed-argv, just without the extra Windows Firewall rule). See
' backend\README.md if you want to run elevated instead.

Option Explicit

Dim fso, root, logsDir, wmi, startup, pidFile, pidStream

Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
logsDir = root & "\logs"
If Not fso.FolderExists(logsDir) Then fso.CreateFolder(logsDir)

Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_
startup.ShowWindow = 0 ' SW_HIDE -- no window is ever created for these processes

pidFile = logsDir & "\running_pids.txt"
Set pidStream = fso.OpenTextFile(pidFile, 2, True) ' 2 = ForWriting (overwrite), create if missing

LaunchHidden wmi, startup, pidStream, _
    "cmd /c call start_backend.bat >> """ & logsDir & "\backend.log"" 2>&1", _
    root & "\backend"

LaunchHidden wmi, startup, pidStream, _
    "cmd /c call start_frontend.bat >> """ & logsDir & "\frontend.log"" 2>&1", _
    root & "\chaos"

If fso.FileExists(root & "\ai_tutor_backend\app.py") Then
    LaunchHidden wmi, startup, pidStream, _
        "cmd /c call start_ai_tutor.bat >> """ & logsDir & "\ai_tutor.log"" 2>&1", _
        root & "\ai_tutor_backend"
End If

pidStream.Close

WScript.Sleep 8000
CreateObject("WScript.Shell").Run "http://localhost:5173", 1, False

Sub LaunchHidden(wmiSvc, startupInfo, pidOut, cmdLine, workDir)
    Dim pid, result
    pid = 0
    result = wmiSvc.Get("Win32_Process").Create(cmdLine, workDir, startupInfo, pid)
    If result = 0 Then
        pidOut.WriteLine pid
    Else
        MsgBox "Chaos Tutor: failed to start a component (error code " & result & ")." & vbCrLf & _
               "Command: " & cmdLine & vbCrLf & vbCrLf & _
               "Make sure Python and Node.js are installed and on PATH.", 48, "Chaos Tutor"
    End If
End Sub
