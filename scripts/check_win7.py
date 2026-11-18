"""Read-only deployment checks, using only Python 3.7 standard library at entry."""

from __future__ import print_function

import importlib
import os
from pathlib import Path
import struct
import sys
import traceback
from html.parser import HTMLParser


ROOT = Path(__file__).resolve().parent.parent


def configure_runtime():
    """Find native DLLs when this script is invoked without the batch launcher."""
    runtime = Path(sys.executable).resolve().parent
    entries = [str(runtime), str(runtime / "Library" / "bin"),
               str(runtime / "Scripts")]
    # A venv created from a Conda environment still loads native DLLs (sqlite3,
    # OpenSSL, ...) from the base prefix; read pyvenv.cfg so the venv works
    # without activating Conda first.
    config = runtime.parent / "pyvenv.cfg"
    if config.is_file():
        try:
            for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, value = line.partition("=")
                if key.strip().lower() == "home" and value.strip():
                    base = Path(value.strip())
                    entries.extend([str(base), str(base / "Library" / "bin")])
                    break
        except Exception:
            pass
    os.environ["PATH"] = os.pathsep.join(entries + [os.environ.get("PATH", "")])
    os.environ["PYTHONNOUSERSITE"] = "1"
    sys.dont_write_bytecode = True


def report(message):
    print(message, flush=True)


class _Assets(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.paths = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "script" and attributes.get("src"):
            self.paths.append(attributes["src"])
        elif tag == "link" and "stylesheet" in attributes.get("rel", "").split():
            if attributes.get("href"):
                self.paths.append(attributes["href"])


def check_environment(root=ROOT, initialize_ocr=True):
    """Return True on success. Never import app.main: its import changes data."""
    configure_runtime()
    root = Path(root).resolve()
    failed = []

    def fail(message):
        failed.append(message)
        report("[FAIL] " + message)

    report("Python: {}".format(sys.executable))
    report("Version: {} ({} bit)".format(sys.version.split()[0], struct.calcsize("P") * 8))
    if sys.version_info[:2] != (3, 7):
        fail("This deployment requires Python 3.7 from CF37v2.")
    if struct.calcsize("P") * 8 != 64:
        fail("This deployment requires 64-bit Python and 64-bit Windows.")
    if sys.platform != "win32":
        fail("This launcher targets Windows 7 SP1 x64 (or newer Windows for testing).")
    else:
        windows = sys.getwindowsversion()
        report("Windows: {}.{} build {}, SP{}".format(
            windows.major, windows.minor, windows.build, windows.service_pack_major))
        if (windows.major, windows.minor) < (6, 1):
            fail("Windows versions older than Windows 7 are unsupported.")
        elif (windows.major, windows.minor) == (6, 1) and windows.service_pack_major < 1:
            fail("Windows 7 SP1 is required; this machine has Windows 7 without SP1.")
        elif (windows.major, windows.minor) != (6, 1):
            report("[INFO] This is not Windows 7; native DLL compatibility still needs a Win7 SP1 check.")

    frontend = root / "frontend" / "dist"
    index = frontend / "index.html"
    if not index.is_file():
        fail("Missing frontend/dist/index.html. Copy the prebuilt frontend/dist folder.")
    else:
        try:
            parser = _Assets()
            parser.feed(index.read_text(encoding="utf-8"))
            if not parser.paths:
                fail("frontend/dist/index.html has no built JavaScript/CSS assets.")
            for asset in parser.paths:
                if asset.startswith(("http://", "https://", "//", "data:")):
                    continue
                asset = asset.split("?", 1)[0].split("#", 1)[0]
                candidate = (frontend / asset.lstrip("/")).resolve()
                if frontend.resolve() not in candidate.parents or not candidate.is_file():
                    fail("Missing or invalid frontend asset: {}".format(asset))
            report("[OK] Built frontend files checked.")
        except Exception:
            fail("Cannot read the built frontend.")
            traceback.print_exc()

    users = root / "backend" / "users.xlsx"
    if not users.is_file():
        fail("Missing backend/users.xlsx; login requires the supplied user workbook.")

    # Compile without executing, writing bytecode, or triggering project migration.
    try:
        sources = sorted((root / "backend" / "app").rglob("*.py"))
        if not sources:
            raise RuntimeError("No backend/app Python source files found")
        for source in sources:
            compile(source.read_bytes(), str(source), "exec")
        report("[OK] Backend source syntax checked with this Python interpreter.")
    except Exception:
        fail("Backend source is incompatible with this interpreter.")
        traceback.print_exc()

    modules = {}
    dependencies = (
        "numpy", "cv2", "onnxruntime", "rapidocr_onnxruntime", "jieba.posseg",
        "pydantic", "typing_extensions", "fastapi", "uvicorn", "multipart",
        "openpyxl", "xlrd", "chardet",
    )
    for name in dependencies:
        try:
            module = importlib.import_module(name)
            modules[name] = module
            report("[OK] Import {} {}".format(name, getattr(module, "__version__", "")))
        except Exception:
            fail("Cannot import {} (full error follows).".format(name))
            traceback.print_exc()

    if "pydantic" in modules:
        model = modules["pydantic"].BaseModel
        if not hasattr(model, "model_dump") or not hasattr(model, "model_validate"):
            fail("The backend requires Pydantic 2 (model_dump/model_validate are missing).")

    if users.is_file() and "openpyxl" in modules:
        workbook = None
        try:
            workbook = modules["openpyxl"].load_workbook(
                str(users), read_only=True, data_only=True)
            sheet = workbook.active
            if sheet.max_column < 4:
                raise ValueError("Expected four columns: username, password, role, name")
            count = sum(1 for row in sheet.iter_rows(min_row=2, values_only=True)
                        if row[0] and row[1])
            if not count:
                raise ValueError("No usable login accounts in users.xlsx")
            report("[OK] User workbook is readable; {} usable account(s).".format(count))
        except Exception:
            fail("User workbook cannot be used for login (account values are not displayed).")
            traceback.print_exc()
        finally:
            if workbook is not None:
                workbook.close()

    if initialize_ocr and "rapidocr_onnxruntime" in modules:
        try:
            report("[INFO] Initializing RapidOCR with the supplied ONNX model files...")
            engine = modules["rapidocr_onnxruntime"].RapidOCR()
            if engine is None:
                raise RuntimeError("RapidOCR initialization returned no engine")
            del engine
            report("[OK] RapidOCR models initialized.")
        except Exception:
            fail("RapidOCR initialization failed; OCR is not ready.")
            traceback.print_exc()

    if failed:
        report("[ERROR] {} check(s) failed. See the exact errors above.".format(len(failed)))
        report("Dependency repair: start with scripts/prepare_win7.py --install-offline")
        report("using the supplied wheelhouse-win7 and backend/requirements-win7.txt.")
        report("Missing DLLs may require the Windows updates / VC++ runtime in the Win7 guide.")
        return False
    report("[OK] Environment checks passed." if initialize_ocr else
           "[OK] Preflight checks passed; application startup will initialize RapidOCR.")
    return True


if __name__ == "__main__":
    sys.exit(0 if check_environment() else 1)
