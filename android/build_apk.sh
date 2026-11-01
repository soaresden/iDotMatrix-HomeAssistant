#!/bin/bash
# Builds android/dist/PixelStudio.apk (debug-signed: installable by hand, not on the Play Store).
# Linux or WSL, with the Android SDK in $ANDROID_HOME (default ~/android-sdk), Gradle 8.10
# (default ~/gradle-8.10.2) and Python 3.13 for Chaquopy (CHAQUOPY_BUILD_PYTHON, default python3.13).
# Builds in a copy on the Linux disk (Gradle is slow and locks badly on a Windows drive).
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
work="${PIXELMETEO_WORK:-$HOME/build/pixelmeteo}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
export CHAQUOPY_BUILD_PYTHON="${CHAQUOPY_BUILD_PYTHON:-$(command -v python3.13 || ls "$HOME"/.local/share/uv/python/cpython-3.13*/bin/python3.13 | head -1)}"
gradle="${GRADLE:-$HOME/gradle-8.10.2/bin/gradle}"

mkdir -p "$work/custom_components"
rsync -a --delete --exclude build --exclude .gradle --exclude dist "$repo/android/" "$work/android/"
# The Studio (the integration's modules) and the PC app's server, copied in by Gradle.
rsync -a --delete --exclude __pycache__ "$repo/custom_components/idotmatrix/" "$work/custom_components/idotmatrix/"
rsync -a --delete --exclude __pycache__ "$repo/desktop/" "$work/desktop/"
echo "sdk.dir=$ANDROID_HOME" > "$work/android/local.properties"
(cd "$work/android" && "$gradle" --no-daemon -q assembleDebug)
mkdir -p "$repo/android/dist"
cp "$work/android/app/build/outputs/apk/debug/app-debug.apk" "$repo/android/dist/PixelStudio.apk"
ls -la "$repo/android/dist/PixelStudio.apk"
