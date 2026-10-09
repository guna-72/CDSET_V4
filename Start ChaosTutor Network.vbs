' Start ChaosTutor Network.vbs
'
' Double-click this file to start Chaos Tutor on Windows in NETWORK mode.
'   - Binds backend to 0.0.0.0:8090 and enables CORS for network clients.
'   - Vite frontend listens on all network interfaces (port 5173).
'   - AI Tutor backend listens on all interfaces (port 5000).
'   - All processes run cleanly in background with logs in logs\.
'   - Shows a notification with your network IP and opens the browser.
'   - Stop with "Stop ChaosTutor.vbs".

Option Explicit

Dim fso, root, logsDir, wmi, startup, pidFile, pidStream, lanIp, shell

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
logsDir = root & "\logs"
If Not fso.FolderExists(logsDir) Then fso.CreateFolder(logsDir)

Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_
startup.ShowWindow = 0 ' SW_HIDE -- no window is created for background processes

pidFile = logsDir & "\running_pids.txt"
Set pidStream = fso.OpenTextFile(pidFile, 2, True) ' 2 = ForWriting (overwrite)

' 1. Backend with 0.0.0.0 host binding and wildcard CORS
LaunchHidden wmi, startup, pidStream, _
    "cmd /c set HOST=0.0.0.0&& set CHAOS_TUTOR_CORS_ORIGINS=*&& call start_backend.bat >> """ & logsDir & "\backend.log"" 2>&1", _
    root & "\backend"

' 2. Frontend Vite dev server
LaunchHidden wmi, startup, pidStream, _
    "cmd /c call start_frontend.bat >> """ & logsDir & "\frontend.log"" 2>&1", _
    root & "\chaos"

' 3. Dedicated AI Tutor service (Flask)
If fso.FileExists(root & "\ai_tutor_backend\app.py") Then
    LaunchHidden wmi, startup, pidStream, _
        "cmd /c call start_ai_tutor.bat >> """ & logsDir & "\ai_tutor.log"" 2>&1", _
        root & "\ai_tutor_backend"
End If

pidStream.Close

lanIp = GetLanIp(wmi)

Dim showMsg, openBrowser, i, arg
showMsg = True
openBrowser = True

If WScript.Arguments.Count > 0 Then
    For i = 0 To WScript.Arguments.Count - 1
        arg = LCase(WScript.Arguments(i))
        If arg = "/nomsg" Or arg = "-nomsg" Then
            showMsg = False
            openBrowser = False
        End If
        If arg = "/nobrowser" Or arg = "-nobrowser" Then
            openBrowser = False
        End If
    Next
End If

If openBrowser Then
    WScript.Sleep 8000
    shell.Run "http://" & lanIp & ":5173", 1, False
End If

If showMsg Then
    MsgBox "Chaos Tutor is now running in Network Mode!" & vbCrLf & vbCrLf & _
           "Local URL (this computer):" & vbCrLf & _
           "  http://localhost:5173" & vbCrLf & vbCrLf & _
           "Network URL (phones, tablets, other PCs on same Wi-Fi/LAN):" & vbCrLf & _
           "  http://" & lanIp & ":5173" & vbCrLf & vbCrLf & _
           "Backend API:" & vbCrLf & _
           "  http://" & lanIp & ":8090" & vbCrLf & vbCrLf & _
           "To stop Chaos Tutor at any time, double-click ""Stop ChaosTutor.vbs"".", _
           64, "Chaos Tutor - Network Mode"
End If

Function GetLanIp(wmiSvc)
    Dim nicConfig, nic, item, bestIp
    bestIp = "127.0.0.1"
    On Error Resume Next
    Set nicConfig = wmiSvc.ExecQuery("Select IPAddress, IPEnabled, DefaultIPGateway from Win32_NetworkAdapterConfiguration where IPEnabled=True")
    If Err.Number = 0 And Not (nicConfig Is Nothing) Then
        For Each nic in nicConfig
            If Not IsNull(nic.IPAddress) Then
                For Each item in nic.IPAddress
                    If InStr(item, ".") > 0 And Left(item, 4) <> "127." And Left(item, 8) <> "169.254." Then
                        bestIp = item
                        If Not IsNull(nic.DefaultIPGateway) Then
                            GetLanIp = bestIp
                            Exit Function
                        End If
                    End If
                Next
            End If
        Next
    End If
    GetLanIp = bestIp
End Function

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
