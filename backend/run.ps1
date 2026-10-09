# Chaos Tutor backend launcher for Windows PowerShell
$ErrorActionPreference = "Stop"
if (Get-Command python -ErrorAction SilentlyContinue) {
    try {
        & python --version | Out-Null
        python -m app.main
    } catch {
        py -m app.main
    }
} else {
    py -m app.main
}

