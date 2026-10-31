# ComfyUI MixMedia для Windows
#
# Ставит ComfyUI, venv, ноды MixMedia и воркфлоу в одну папку, кладёт ярлык на рабочий стол.
# Запуск: правый клик по файлу -> "Выполнить с помощью PowerShell", или:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Не проверено на живой Windows: если что-то упадёт — пришли текст ошибки.

param(
    [string]$InstallDir = "$env:USERPROFILE\ComfyUI-MixMedia",
    [string]$ComfyUI = "",
    [string]$Key = "",
    [switch]$Cpu
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Step($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[+] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# ---------------------------------------------------------------- python
Step "Ищу Python 3.11+"
$pyExe = $null
$pyArg = @()
foreach ($cand in @("py -3.12", "py -3.11", "py -3.10", "python")) {
    $parts = $cand -split " "
    $exe = $parts[0]
    $arg = @($parts | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try {
        $ver = & $exe @arg -c "import sys; print(str(sys.version_info[0])+'.'+str(sys.version_info[1]))" 2>$null
    } catch { continue }
    if ($ver -match '^3\.(1[1-9])$') {
        $pyExe = $exe
        $pyArg = $arg
        Ok "Python $ver ($cand)"
        break
    }
}
if (-not $pyExe) {
    throw "Не найден Python 3.11+. Поставь с https://python.org (галочка 'Add python.exe to PATH') и запусти снова."
}

# ---------------------------------------------------------------- comfyui
if ($ComfyUI) {
    $comfyPath = (Resolve-Path $ComfyUI).Path
    Ok "Беру готовый ComfyUI: $comfyPath"
} else {
    $comfyPath = Join-Path $InstallDir "ComfyUI"
    if (Test-Path (Join-Path $comfyPath "main.py")) {
        Ok "ComfyUI уже на месте: $comfyPath"
    } else {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            throw "Нет git. Поставь Git for Windows (https://git-scm.com) или укажи готовый ComfyUI через -ComfyUI."
        }
        Step "Клонирую ComfyUI в $comfyPath"
        git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git $comfyPath
    }
}

# ---------------------------------------------------------------- venv
$venv = Join-Path $InstallDir "venv"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    Step "Создаю venv"
    & $pyExe @pyArg -m venv $venv
}
& $py -m pip install --upgrade pip | Out-Null

if ($Cpu) {
    Step "Ставлю torch (CPU) — долго, ~1.5 ГБ"
    & $py -m pip install torch torchvision torchaudio
} else {
    Step "Ставлю torch (CUDA 12.4) — долго, ~2.5 ГБ"
    & $py -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
}
Step "Ставлю зависимости ComfyUI"
& $py -m pip install -r (Join-Path $comfyPath "requirements.txt")
& $py -m pip install requests pillow numpy

# ---------------------------------------------------------------- nodes + workflow
Step "Копирую ноды MixMedia"
$nodesSrc = Join-Path $here "custom_nodes\comfyui-mixmedia"
$nodesDst = Join-Path $comfyPath "custom_nodes\comfyui-mixmedia"
if (Test-Path $nodesSrc) {
    if (Test-Path $nodesDst) { Remove-Item -Recurse -Force $nodesDst }
    Copy-Item -Recurse -Force $nodesSrc $nodesDst
    Ok "Ноды в $nodesDst"
} else {
    Warn "В архиве нет custom_nodes\comfyui-mixmedia — возьми его из репозитория"
}

$wfSrc = Join-Path $here "workflows\photostudio_mixmedia.json"
if (Test-Path $wfSrc) {
    $wfDst = Join-Path $comfyPath "user\default\workflows"
    New-Item -ItemType Directory -Force -Path $wfDst | Out-Null
    Copy-Item -Force $wfSrc $wfDst
    Ok "Воркфлоу в $wfDst"
}

# ---------------------------------------------------------------- key
$keyPath = Join-Path $env:USERPROFILE ".mixmedia_key"
if ($Key) {
    Set-Content -Path $keyPath -Value $Key -NoNewline -Encoding ascii
    Ok "Ключ MixMedia записан в $keyPath"
} elseif (-not (Test-Path $keyPath)) {
    Warn "Ключа нет. Положи его одной строкой в $keyPath (или запусти install.ps1 -Key ...)"
}

# ---------------------------------------------------------------- launcher + shortcut
Step "Готовлю запуск"
Copy-Item -Force (Join-Path $here "start.bat") (Join-Path $InstallDir "start.bat")
$startBat = Join-Path $InstallDir "start.bat"

$shell = New-Object -ComObject WScript.Shell
$lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "ComfyUI MixMedia.lnk"
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $startBat
$lnk.WorkingDirectory = $InstallDir
$lnk.Description = "ComfyUI + MixMedia: фотостудия"
$lnk.IconLocation = "$env:SystemRoot\System32\shell32.dll,325"
$lnk.Save()
Ok "Ярлык на рабочем столе: $lnkPath"

$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "ComfyUI MixMedia.lnk"
$lnk2 = $shell.CreateShortcut($startMenu)
$lnk2.TargetPath = $startBat
$lnk2.WorkingDirectory = $InstallDir
$lnk2.Save()

Write-Host ""
Ok "Готово. Запуск: ярлык 'ComfyUI MixMedia' на рабочем столе."
Write-Host "   ComfyUI: $comfyPath"
Write-Host "   venv:    $venv"
Write-Host "   лог:     $env:LOCALAPPDATA\ComfyUI Mix Media\server.log"
