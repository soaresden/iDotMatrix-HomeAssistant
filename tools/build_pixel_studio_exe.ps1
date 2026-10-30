# Builds dist\PixelStudio.exe: Pixel Studio on a PC, in a single file holding
# Python, aiohttp, bleak with the Windows Bluetooth runtime (WinRT), Pillow,
# the integration's Studio code and panel, and desktop\ (the server, the
# Home Assistant stand-in, the page with the Bluetooth bar).
# Nothing to install where it runs (Windows 10/11 with Bluetooth LE).
#
#   powershell -ExecutionPolicy Bypass -File tools\build_pixel_studio_exe.ps1 [-Python C:\path\to\python.exe]
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$integration = "$root\custom_components\idotmatrix"

& $Python -m pip install --quiet "bleak==3.0.2" "bleak-retry-connector==4.7.0" "pillow==12.3.0" `
    cryptography voluptuous aiohttp pyinstaller
if ($LASTEXITCODE) { exit $LASTEXITCODE }

# The Studio modules as the package idmcore (see desktop\pixel_studio.py):
# not the integration's __init__ (Home Assistant), coordinator (replaced by
# desktop\overrides) or Store tab (it needs the official app's key, never shipped).
$pkg = "$root\build\pkg\idmcore"
if (Test-Path $pkg) { Remove-Item -Recurse -Force $pkg }
New-Item -ItemType Directory -Force "$pkg\www" | Out-Null
Set-Content -Path "$pkg\__init__.py" -Value "" -Encoding utf8
foreach ($module in "studio", "journal", "routines", "schedule", "media", "weather", "preview", "const") {
    Copy-Item "$integration\$module.py" $pkg
}
Copy-Item -Recurse "$integration\client" "$pkg\client"
Get-ChildItem -Recurse -Directory -Filter __pycache__ $pkg | Remove-Item -Recurse -Force
Copy-Item "$integration\www\idotmatrix-studio.js" "$pkg\www"
Copy-Item "$root\desktop\overrides\coordinator.py" $pkg

# The window icon, from the repository's.
& $Python -c "from PIL import Image; Image.open(r'$root\icon.png').save(r'$root\build\pixel_studio.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])"
if ($LASTEXITCODE) { exit $LASTEXITCODE }

# idmcore is imported by name at run time (importlib): its modules are listed.
$modules = "studio", "journal", "routines", "schedule", "media", "weather", "preview", "const", "coordinator" |
    ForEach-Object { "--hidden-import=idmcore.$_" }
& $Python -m PyInstaller --noconfirm --onefile --console --name PixelStudio `
    --icon "$root\build\pixel_studio.ico" `
    --distpath "$root\dist" --workpath "$root\build\pyinstaller" --specpath "$root\build" `
    --paths "$root\desktop" --paths "$root\build\pkg" `
    @modules --collect-submodules idmcore.client --collect-submodules homeassistant `
    --collect-submodules bleak --collect-submodules winrt `
    --add-data "$pkg\www;idmcore\www" --add-data "$root\desktop\index.html;." `
    "$root\desktop\pixel_studio.py"
exit $LASTEXITCODE
