"""Prepare or repair the local CPython 3.7 x64 offline environment."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
WHEELS = ROOT / "wheelhouse-win7"
REQUIREMENTS = ROOT / "backend" / "requirements-win7.txt"


def runtime_environment(runtime):
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join([
        str(runtime), str(runtime / "Library" / "bin"),
        str(runtime / "Scripts"), environment.get("PATH", ""),
    ])
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def wheel_hashes():
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(WHEELS.glob("*.whl"))
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--download-wheels", action="store_true",
                       help="Internet required; collect Python 3.7 x64 wheels")
    modes.add_argument("--install-offline", action="store_true",
                       help="Install from the supplied wheelhouse; no network")
    parser.add_argument("--index-url", default="https://pypi.org/simple")
    parser.add_argument("--direct", action="store_true",
                       help="Bypass proxies for this download only")
    parser.add_argument("--python", metavar="PYTHON_EXE",
                       help="Target interpreter; defaults to CF37v2 inside/beside "
                            "the project, then the interpreter running this script")
    args = parser.parse_args()
    if args.python:
        interpreter = Path(args.python).resolve()
        if not interpreter.is_file():
            parser.error("--python does not point to a file: {}".format(interpreter))
        runtime = interpreter.parent
    else:
        candidates = (ROOT / "CF37v2", ROOT.parent / "CF37v2",
                      Path(sys.executable).resolve().parent)
        runtime = next((path for path in candidates
                        if (path / "python.exe").is_file()), None)
        if runtime is None:
            parser.error("No Python runtime found. Put CF37v2 inside or beside the "
                         "project, or pass --python <path to python.exe>.")
        interpreter = runtime / "python.exe"
    environment = runtime_environment(runtime)
    if Path(sys.executable).resolve() != interpreter.resolve():
        return subprocess.call([str(interpreter), str(Path(__file__).resolve())]
                               + sys.argv[1:], env=environment)
    if sys.version_info[:2] != (3, 7) or struct.calcsize("P") != 8:
        parser.error("CF37v2 must contain CPython 3.7 x64.")
    command = [str(interpreter), "-m", "pip", "--isolated"]
    if args.download_wheels:
        if args.direct:
            environment["NO_PROXY"] = "*"
            environment["no_proxy"] = "*"
        WHEELS.mkdir(exist_ok=True)
        result = subprocess.call(command + [
            "wheel", "--disable-pip-version-check", "--prefer-binary",
            "--index-url", args.index_url, "--wheel-dir", str(WHEELS),
            "-r", str(REQUIREMENTS),
        ], env=environment)
        if result:
            return result
        hashes = wheel_hashes()
        if not hashes:
            raise RuntimeError("No wheels were downloaded.")
        (WHEELS / "SHA256.json").write_text(
            json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
        print("[OK] Saved {} wheels and SHA256.json.".format(len(hashes)))
        return 0

    manifest = WHEELS / "SHA256.json"
    if not manifest.is_file():
        parser.error("Missing wheelhouse-win7/SHA256.json; prepare wheels on the online PC first.")
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    actual = wheel_hashes()
    if not expected or set(actual) != set(expected) or any(actual.get(name) != checksum
                           for name, checksum in expected.items()):
        parser.error("An offline wheel is missing or damaged. Copy the complete wheelhouse again.")
    result = subprocess.call(command + [
        "install", "--disable-pip-version-check", "--no-index",
        "--force-reinstall", "--only-binary=:all:", "--find-links", str(WHEELS),
        "-r", str(REQUIREMENTS),
    ], env=environment)
    if result:
        return result
    result = subprocess.call(command + ["check"], env=environment)
    if result:
        return result
    return subprocess.call([str(interpreter), "-B", str(ROOT / "scripts" / "check_win7.py")],
                           env=environment)


if __name__ == "__main__":
    sys.exit(main())
