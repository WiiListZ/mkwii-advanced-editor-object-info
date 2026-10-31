"""Build the portable Windows executable with all UI assets and offline documentation."""

import hashlib
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="dist", help="Output folder (use another folder if an older executable is running)")
    args = parser.parse_args()
    output = (ROOT / args.output_dir).resolve()
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-v"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/validate.py"], cwd=ROOT, check=True)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--name", "ObjectInfoEditor", "--icon", "assets/icon.ico",
        "--distpath", str(output),
        "--collect-all", "customtkinter", "--collect-all", "PIL",
        "--add-data", "assets;assets", "--add-data", "data/baseline.json;data",
        "objinfo_editor.py",
    ], cwd=ROOT, check=True)
    exe = output / "ObjectInfoEditor.exe"
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    (exe.with_suffix(".exe.sha256")).write_text(f"{digest}  {exe.name}\n", encoding="utf-8")
    shutil.copyfile(ROOT / "README.md", output / "README.md")
    print(f"Built {exe} ({exe.stat().st_size:,} bytes)\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
