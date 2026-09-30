"""
Packaging script for GhostScribe - Portable Distribution Generator
Creates a clean, sanitized 'GhostScribe_Portable.zip' ready for distribution to other users.

Strictly excludes:
- .env (guarantees NO API keys are leaked!)
- .venv (each user builds their own python environment via start.bat)
- Any previous recordings (wav, mp3)
- Any previous meeting summaries (md, json)
- Cache directories (__pycache__)
"""

import os
import zipfile

OUTPUT_ZIP = "GhostScribe_Portable.zip"

INCLUDED_ROOT_FILES = [
    "main.py",
    "app.py",
    "recorder.py",
    "analyzer.py",
    "cli.py",
    "utils.py",
    "list_devices.py",
    "requirements.txt",
    "start.bat",
    "install_requirements.bat",
    "create_zip.bat",
    "create_portable_zip.py",
    "pyproject.toml",
    ".gitignore",
    ".env.example",
    "README.md",
    "LICENSE",
]

INCLUDED_DIRS = {
    "static": ["index.html", "style.css", "app.js", "logo.png"],
}

EMPTY_DIRS = ["meetings", "recordings"]


def create_portable_zip():
    print("=" * 65)
    print(">> GHOSTSCRIBE - PORTABLE DISTRIBUTION PACKAGER")
    print("=" * 65)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    zip_path = os.path.join(base_dir, OUTPUT_ZIP)

    # Remove previous zip if exists
    if os.path.exists(zip_path):
        os.remove(zip_path)

    print(f"\n[1/3] Sammle Dateien in {base_dir} ...\n")

    files_to_pack = []

    # 1. Root files
    for fname in INCLUDED_ROOT_FILES:
        fpath = os.path.join(base_dir, fname)
        if os.path.exists(fpath):
            files_to_pack.append((fpath, fname))
        else:
            print(f"  [WARNUNG] Datei fehlt: {fname}")

    # 2. Subdirectories
    for dname, fnames in INCLUDED_DIRS.items():
        for fname in fnames:
            rel_path = os.path.join(dname, fname)
            fpath = os.path.join(base_dir, rel_path)
            if os.path.exists(fpath):
                files_to_pack.append((fpath, rel_path.replace("\\", "/")))
            else:
                print(f"  [WARNUNG] Datei fehlt: {rel_path}")

    # 3. Create ZIP
    print(f"[2/3] Erstelle Archiv: {OUTPUT_ZIP} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_p, arc_p in files_to_pack:
            size_kb = os.path.getsize(abs_p) / 1024.0
            print(f"  + Hinzufuegen: {arc_p:<30} ({size_kb:6.1f} KB)")
            zf.write(abs_p, arc_p)

        # Empty placeholder directories
        for d in EMPTY_DIRS:
            placeholder_arc = f"{d}/.gitkeep"
            zf.writestr(placeholder_arc, "")
            print(f"  + Ordner (leer): {d}/")

    # 4. Rigorous Security Audit of the ZIP
    print("\n[3/3] Fuehre Sicherheits-Pruefung durch...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()

        # Security check 1: NO .env file!
        for name in namelist:
            if name == ".env" or name.endswith("/.env"):
                os.remove(zip_path)
                raise RuntimeError("KRITISCHER FEHLER: '.env' wurde im Archiv gefunden! Vorgang abgebrochen.")

            if ".venv" in name:
                os.remove(zip_path)
                raise RuntimeError("KRITISCHER FEHLER: '.venv' wurde im Archiv gefunden! Vorgang abgebrochen.")

            if name.endswith((".wav", ".mp3")):
                os.remove(zip_path)
                raise RuntimeError(f"KRITISCHER FEHLER: Audiodatei '{name}' gefunden! Vorgang abgebrochen.")

            if name.startswith("meetings/") and not name.endswith(".gitkeep"):
                os.remove(zip_path)
                raise RuntimeError(f"KRITISCHER FEHLER: Privates Meeting-Protokoll '{name}' gefunden!")

    total_size_kb = os.path.getsize(zip_path) / 1024.0
    print("\n" + "=" * 65)
    print(f"[OK] '{OUTPUT_ZIP}' wurde erfolgreich erstellt!")
    print(f"     Dateigroesse: {total_size_kb:.1f} KB")
    print(f"     Dateien im Archiv: {len(namelist)}")
    print("     Sicherheits-Check: BESTANDEN (Keine Keys, keine Aufnahmen enthalten)")
    print("=" * 65)
    print("\nDu kannst diese ZIP-Datei nun einfach an andere weitergeben.")
    print("Der Empfaenger muss sie nur entpacken und 'start.bat' doppelklicken!\n")


if __name__ == "__main__":
    create_portable_zip()
