# Builds dist\send_gif.exe: a single file holding Python, bleak, the Windows
# Bluetooth runtime (WinRT), the integration's BLE client and the test GIFs.
# Nothing to install where it runs (Windows 10/11 with Bluetooth LE).
#
#   powershell -ExecutionPolicy Bypass -File tools\build_send_gif_exe.ps1 [-Python C:\path\to\python.exe]
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

& $Python -m pip install --quiet "bleak==3.0.2" "bleak-retry-connector==4.7.0" "pillow==12.3.0" cryptography pyinstaller
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $Python "$root\tools\make_test_gifs.py" "$root\build\test_gifs"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
# The media converter as a package of its own (send_gif.load_media): the
# integration package's __init__ needs Home Assistant.
$media = "$root\build\pkg\idmcore"
New-Item -ItemType Directory -Force $media | Out-Null
Set-Content -Path "$media\__init__.py" -Value "" -Encoding utf8
Copy-Item "$root\custom_components\idotmatrix\media.py", "$root\custom_components\idotmatrix\weather.py" $media
& $Python -m PyInstaller --noconfirm --onefile --console --name send_gif `
    --distpath "$root\dist" --workpath "$root\build\pyinstaller" --specpath "$root\build" `
    --paths "$root\custom_components\idotmatrix" --paths "$root\build\pkg" `
    --collect-submodules client --collect-submodules bleak --collect-submodules winrt `
    --hidden-import idmcore.media `
    --add-data "$root\build\test_gifs;test_gifs" `
    "$root\tools\send_gif.py"
exit $LASTEXITCODE
