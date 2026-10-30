"""Send a GIF to an iDotMatrix display from this computer's Bluetooth, without
Home Assistant: the proof of concept for a standalone Pixel Studio.

    python tools/send_gif.py path/to/file.gif [--size 64] [--address XX:XX:XX:XX:XX:XX]
    python tools/send_gif.py --scan

Needs bleak, bleak-retry-connector and Pillow. The display takes one Bluetooth
controller at a time: Home Assistant (or the phone app) must not be connected
to it meanwhile.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
import sys
import tempfile
import types
from pathlib import Path
from time import monotonic

# The client library and the media converter are imported on their own: the
# integration package around them (custom_components/idotmatrix/__init__.py)
# needs Home Assistant.
LIBRARY = Path(__file__).resolve().parents[1] / "custom_components" / "idotmatrix"
# Built as an .exe (PyInstaller): started by a double click or a GIF dropped
# on it, in a console window that closes when it ends.
FROZEN = getattr(sys, "frozen", False)
SIZES = (64, 32, 16)


def load_client():
    """(ConnectionManager, Gif) from the integration's BLE client library."""
    if str(LIBRARY) not in sys.path:
        sys.path.insert(0, str(LIBRARY))
    from client.connectionManager import ConnectionManager
    from client.modules.gif import Gif
    return ConnectionManager, Gif


def load_media():
    """The integration's media.py (and the weather.py encoder it uses).

    The .exe bundles both as the package ``idmcore``; from the source tree
    that package points at the integration folder without running its
    ``__init__``."""
    if not FROZEN and "idmcore" not in sys.modules:
        package = types.ModuleType("idmcore")
        package.__path__ = [str(LIBRARY)]
        sys.modules["idmcore"] = package
    return importlib.import_module("idmcore.media")


def fit_to_screen(path: str, size: int | None, out=print) -> str:
    """The file itself when it is already a GIF of the screen's size, else a
    copy converted like the gallery does (crop to square, 96 KB budget)."""
    if not size:
        return path
    from PIL import Image
    try:
        with Image.open(path) as image:
            if image.format == "GIF" and image.size == (size, size):
                return path
    except OSError:
        pass  # not an image: media.convert tries it as a video
    media = load_media()
    try:
        result = media.convert(path, media.ConvertOptions(size=size))
    except FileNotFoundError as err:  # no ffmpeg next to the .exe
        raise ValueError(f"{os.path.basename(path)} : format non pris en charge (GIF ou image seulement)") from err
    target = Path(tempfile.gettempdir()) / f"idotmatrix-{size}px-{Path(path).stem}.gif"
    target.write_bytes(result.data)
    out(f"{os.path.basename(path)} adapte a {size}x{size} : {result.size_bytes // 1024} Ko, {result.frames} images")
    return str(target)


def _median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else None


def _s(value):
    return "-" if value is None else f"{value:.3f}"


def summarize(report: dict, *, per_packet: bool = True) -> list[str]:
    """Readable lines from a ConnectionManager transfer report."""
    kb, seconds, packets = report["bytes"] / 1024, report.get("seconds") or 0, report["packets"]
    lines = [
        f"Transfert : {packets} paquets, {kb:.0f} Ko en {seconds:.1f} s"
        + (f" ({kb / seconds:.1f} Ko/s, {seconds / packets:.2f} s par paquet de 4 Ko)" if seconds and packets else ""),
        f"Ecritures : {report.get('write_size')} octets, rafale={report.get('write_burst')}, "
        f"pause={report.get('write_pause_s')} s",
    ]
    for number, attempt in enumerate(report["attempts"], 1):
        timings = attempt["packets"]
        writes = [w for w, _ in timings if w is not None]
        waits = [w for _, w in timings if w is not None]
        lines.append(
            f"Essai {number} ({attempt['mode']}) : {len(timings)} paquets, "
            f"ecriture mediane {_s(_median(writes))} s / max {_s(max(writes, default=None))} s, "
            f"attente afficheur mediane {_s(_median(waits))} s / max {_s(max(waits, default=None))} s"
            + (f", ECHEC : {attempt['failed']}" if attempt.get("failed") else "")
        )
        if per_packet:
            cells = [f"{i:>4}: {_s(w)} + {_s(t)}" for i, (w, t) in enumerate(timings, 1)]
            lines += ["  " + "   ".join(cells[i:i + 4]) for i in range(0, len(cells), 4)]
    if report.get("error"):
        lines.append(f"Erreur : {report['error']}")
    return lines


async def scan(manager_cls, out=print) -> list[tuple[str, str]]:
    devices = await manager_cls.scan()
    if not devices:
        out("Aucun afficheur IDM- trouve.")
    for address, name in devices:
        out(f"{name}  {address}")
    return devices


NOT_FOUND = ("Aucun afficheur IDM- trouve : allume-le, approche-le du PC et ferme "
             "l'appli iDotMatrix du telephone (ou deconnecte Home Assistant).")


async def send(path: str, address: str | None, manager_cls, gif_cls, *, out=print, per_packet=True,
               size: int | None = None, pick=None) -> dict:
    """Connect, send one GIF with the single-upload protocol, disconnect.

    Without an address, the display is the only IDM- one in range, or the
    one ``pick`` chooses among several (the first without ``pick``). The file
    is fitted to ``size`` first when given. Returns what matters for the
    standalone decision (timings and reports)."""
    path = fit_to_screen(path, size, out)
    reports = []
    manager_cls.transfer_log = lambda _address, _label, report: reports.append(report)
    manager_cls.transfer_listener = lambda sent, total, _address: print(
        f"\r  paquet {sent}/{total}", end="" if sent < total else "\n", flush=True)
    result = {"file": os.path.basename(path), "bytes": os.path.getsize(path), "size": size}

    started = monotonic()
    if not address:
        devices = await manager_cls.scan()
        if not devices:
            raise ConnectionError(NOT_FOUND)
        address, name = pick(devices) if pick and len(devices) > 1 else devices[0]
        out(f"Afficheur : {name} {address} ({len(devices)} a portee, {monotonic() - started:.1f} s)")
    manager = manager_cls.for_address(address)
    manager.transfer_label = result["file"]
    await manager.connect()
    result.update(
        address=address,
        connect_s=round(monotonic() - started, 2),
        write_size=manager._write_size(),
        mtu=getattr(manager.client, "mtu_size", None),
    )
    out(f"Connecte a {address} en {result['connect_s']:.1f} s (recherche comprise), "
        f"ecritures de {result['write_size']} octets, MTU {result['mtu']}")
    try:
        out(f"Envoi de {result['file']} ({result['bytes'] / 1024:.0f} Ko)...")
        result["ok"] = await gif_cls(manager).uploadSingleRaw(path)
    finally:
        await manager.disconnect()
        manager_cls.transfer_log = manager_cls.transfer_listener = None
    result["reports"] = reports
    for report in reports:
        for line in summarize(report, per_packet=per_packet):
            out(line)
    out("Envoye." if result["ok"] else "Echec de l'envoi (voir le journal ci-dessus).")
    return result


def builtin_gifs() -> list[Path]:
    """Test GIFs packed into the .exe (tools/make_test_gifs.py)."""
    folder = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "test_gifs"
    return sorted(folder.glob("*.gif"))


def choose_builtin(gifs: list[Path], ask=input) -> str | None:
    """The built-in GIF picked in a menu, or None to only look for displays."""
    print("Pour envoyer ton propre GIF (ou une image), fais-le glisser sur send_gif.exe.")
    print("GIFs de test integres (adaptes a la taille de ton cadre s'il le faut) :")
    for number, gif in enumerate(gifs, 1):
        print(f"  {number}. {gif.name} ({gif.stat().st_size // 1024} Ko)")
    print("  0. seulement chercher les afficheurs a portee")
    answer = ask("Ton choix : ").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(gifs):
        return str(gifs[int(answer) - 1])
    return None


def choose_size(saved: int | None, ask=input) -> int:
    """The screen size in pixels, Enter keeping the one used last time."""
    hint = f" [Entree = {saved}]" if saved in SIZES else ""
    while True:
        answer = ask(f"Taille de ton cadre en pixels (64, 32 ou 16){hint} : ").strip()
        if not answer and saved in SIZES:
            return saved
        if answer.isdigit() and int(answer) in SIZES:
            return int(answer)


def choose_display(devices: list[tuple[str, str]], ask=input) -> tuple[str, str]:
    """One of several displays in range (Enter: the first)."""
    print("Plusieurs afficheurs a portee :")
    for number, (address, name) in enumerate(devices, 1):
        print(f"  {number}. {name}  {address}")
    while True:
        answer = ask("Lequel ? [Entree = 1] : ").strip() or "1"
        if answer.isdigit() and 1 <= int(answer) <= len(devices):
            return devices[int(answer) - 1]


def load_settings(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("gif", nargs="?", help="GIF (ou image) a envoyer")
    parser.add_argument("--size", type=int, choices=SIZES,
                        help="taille du cadre : le fichier y est adapte s'il ne l'est pas deja")
    parser.add_argument("--address", help="adresse Bluetooth de l'afficheur (sinon celui a portee)")
    parser.add_argument("--scan", action="store_true", help="lister les afficheurs IDM- a portee")
    parser.add_argument("--report", help="ecrire ce qui s'affiche et le rapport complet (JSON) dans ce fichier"
                        + (" (par defaut rapport-idotmatrix.txt a cote de l'exe)" if FROZEN else ""))
    parser.add_argument("--quiet-packets", action="store_true", help="ne pas detailler chaque paquet")
    parser.add_argument("-v", "--verbose", action="store_true", help="journal BLE detaille")
    args = parser.parse_args(argv)
    interactive = FROZEN or sys.stdin.isatty()
    if not args.scan and not args.gif:
        if not FROZEN:
            parser.error("indique un GIF, ou --scan")
        args.gif = choose_builtin(builtin_gifs())
        args.scan = args.gif is None
    settings_path = Path(sys.executable).with_name("send_gif-reglages.json") if FROZEN else None
    if FROZEN and not args.report:
        args.report = str(Path(sys.executable).with_name("rapport-idotmatrix.txt"))
    if FROZEN and not args.scan and not args.size:
        settings = load_settings(settings_path)
        args.size = choose_size(settings.get("size"))
        try:
            settings_path.write_text(json.dumps({**settings, "size": args.size}), encoding="utf-8")
        except OSError:
            pass  # e.g. the .exe sits in a read-only folder: asked again next time

    # Before the library's own logger setup (DEBUG for everything).
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    lines = []

    def out(line):
        print(line)
        lines.append(line)

    result, code = None, 1
    try:
        manager_cls, gif_cls = load_client()
        if args.scan:
            asyncio.run(scan(manager_cls, out))
            code = 0
        else:
            result = asyncio.run(send(args.gif, args.address, manager_cls, gif_cls, out=out,
                                      per_packet=not args.quiet_packets, size=args.size,
                                      pick=choose_display if interactive else None))
            code = 0 if result["ok"] else 1
    except Exception as err:  # noqa: BLE001 - a CLI says what went wrong
        out(f"Erreur : {err}")
    if args.report:
        text = "\n".join(lines) + ("\n\n" + json.dumps(result, indent=1) if result else "") + "\n"
        Path(args.report).write_text(text, encoding="utf-8")
        print(f"Rapport : {args.report}")
    if FROZEN:
        input("Appuie sur Entree pour fermer.")
    return code


if __name__ == "__main__":
    sys.exit(main())
