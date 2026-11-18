"""Build the Windows 7 x64 offline ZIP without importing or starting the app."""

import argparse
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import time
import zipfile


ROOT = Path(__file__).resolve().parent.parent
TOP_LEVEL = "OCR-Benti-Win7"
OUTPUT = ROOT / "dist" / "OCR-Benti-Win7-x64-offline.zip"
SKIP_DIRECTORIES = {"__pycache__", ".git", "node_modules", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".pdb"}
CHUNK_SIZE = 1024 * 1024


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def require_file(path, allow_empty=False):
    if not path.is_file() or (not allow_empty and path.stat().st_size == 0):
        raise ValueError("Missing or empty required file: {}".format(path))


def read_requirements(path):
    require_file(path)
    packages = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9_.+!-]+)$", line)
        if not match:
            raise ValueError("Requirement line {} must be a simple exact name==version pin.".format(number))
        name, version = normalized(match.group(1)), match.group(2)
        if name in packages:
            raise ValueError("Duplicate requirement: {}".format(name))
        packages[name] = version
    if not packages:
        raise ValueError("No exact package pins found in requirements-win7.txt")
    return packages


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique_json(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate entry in SHA256.json: {}".format(name))
        result[name] = value
    return result


def compatible_wheel(name):
    """Read PEP 427 filename tags for the fixed CPython 3.7 x64 target."""
    parts = name[:-4].split("-")
    if len(parts) not in (5, 6):
        raise ValueError("Invalid wheel filename: {}".format(name))
    package, version = normalized(parts[0]), parts[1]
    python_tags, abi_tags, platform_tags = [part.split(".") for part in parts[-3:]]
    if not {"any", "win_amd64"}.intersection(platform_tags):
        raise ValueError("Wheel is not for Windows x64 / any platform: {}".format(name))
    supported = False
    for python_tag in python_tags:
        for abi in abi_tags:
            if python_tag == "cp37" and abi in ("cp37m", "abi3", "none"):
                supported = True
            elif python_tag.startswith("cp") and abi == "abi3":
                suffix = python_tag[2:]
                if suffix.isdigit() and 32 <= int(suffix) <= 37:
                    supported = True
            elif abi == "none" and (python_tag == "py3" or python_tag in
                                    {"py3{}".format(minor) for minor in range(8)}):
                supported = True
    if not supported:
        raise ValueError("Wheel is not compatible with CPython 3.7: {}".format(name))
    return package, version


def check_wheels(directory, requirements):
    manifest = directory / "SHA256.json"
    require_file(manifest)
    hashes = json.loads(manifest.read_text(encoding="utf-8"), object_pairs_hook=_unique_json)
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("SHA256.json must be a nonempty wheel-filename to SHA256 mapping")
    for name, checksum in hashes.items():
        if (not isinstance(name, str) or not name.endswith(".whl") or
                Path(name).name != name or "/" in name or "\\" in name):
            raise ValueError("Invalid wheel path in SHA256.json: {!r}".format(name))
        if not isinstance(checksum, str) or not re.match(r"^[0-9a-fA-F]{64}$", checksum):
            raise ValueError("Invalid SHA256 value for {}".format(name))
    actual = {path.name for path in directory.glob("*.whl") if path.is_file()}
    if actual != set(hashes):
        raise ValueError("Wheel manifest mismatch; missing: {}; unlisted: {}".format(
            sorted(set(hashes) - actual), sorted(actual - set(hashes))))
    available = {}
    for name in sorted(hashes):
        path = directory / name
        if sha256(path).lower() != hashes[name].lower():
            raise ValueError("Offline wheel checksum mismatch: {}".format(name))
        package, version = compatible_wheel(name)
        available.setdefault(package, set()).add(version)
        with zipfile.ZipFile(str(path)) as wheel:
            damaged = wheel.testzip()
            if damaged:
                raise ValueError("Corrupted wheel member in {}: {}".format(name, damaged))
    for name, version in sorted(requirements.items()):
        if version not in available.get(name, set()):
            raise ValueError("No verified CPython 3.7 x64 wheel for {}=={}".format(name, version))
    return hashes


def check_prerequisites(directory):
    """Verify the supplied installer without executing its bootstrap program."""
    for name in ("VC_redist.x64.exe", "SHA256.json", "SOURCE.txt"):
        require_file(directory / name)
    hashes = json.loads((directory / "SHA256.json").read_text(encoding="utf-8"),
                        object_pairs_hook=_unique_json)
    if not isinstance(hashes, dict) or set(hashes) != {"VC_redist.x64.exe"}:
        raise ValueError("prerequisites/SHA256.json must list exactly VC_redist.x64.exe")
    checksum = hashes["VC_redist.x64.exe"]
    if not isinstance(checksum, str) or not re.match(r"^[0-9a-fA-F]{64}$", checksum):
        raise ValueError("Invalid SHA256 value for prerequisites/VC_redist.x64.exe")
    if sha256(directory / "VC_redist.x64.exe").lower() != checksum.lower():
        raise ValueError("VC_redist.x64.exe checksum mismatch; copy the verified installer again")
    # The x64 installer can have an x86 bootstrap EXE, so machine-type checking
    # belongs to the Python runtime binaries, not this installation program.
    return hashes


def check_amd64_executable(path):
    require_file(path)
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Runtime file is not a Windows PE executable: {}".format(path))
        stream.seek(0x3C)
        header_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(header_offset)
        if stream.read(4) != b"PE\x00\x00" or stream.read(2) != b"\x64\x86":
            raise ValueError("Runtime file is not an AMD64 PE executable: {}".format(path))


def check_runtime(runtime, requirements):
    check_amd64_executable(runtime / "python.exe")
    check_amd64_executable(runtime / "python37.dll")
    require_file(runtime / "Lib" / "os.py")
    site = runtime / "Lib" / "site-packages"
    versions = {}
    for metadata_file in site.glob("*.dist-info/METADATA"):
        metadata = Parser().parsestr(metadata_file.read_text(encoding="utf-8"))
        name, version = metadata.get("Name"), metadata.get("Version")
        if name and version:
            versions.setdefault(normalized(name), set()).add(version)
    for name, version in sorted(requirements.items()):
        installed = versions.get(name, set())
        if installed != {version}:
            raise ValueError("Internal CF37v2 has {} version(s) {}, expected {}. "
                             "Finish offline installation before packaging.".format(
                                 name, sorted(installed), version))
    ocr = site / "rapidocr_onnxruntime"
    require_file(ocr / "config.yaml")
    models = sorted((ocr / "models").glob("*.onnx"))
    if len(models) < 3:
        raise ValueError("RapidOCR requires three supplied detector/classifier/recognizer ONNX models")
    for model in models:
        require_file(model)
    for pattern in ("onnxruntime/capi/onnxruntime_pybind11_state*.pyd", "cv2/**/*.pyd"):
        if not any(site.glob(pattern)):
            raise ValueError("Missing required native extension: {}".format(pattern))


def is_reparse_point(path):
    information = os.lstat(str(path))
    return path.is_symlink() or bool(getattr(information, "st_file_attributes", 0) & 0x400)


def files_in(directory):
    if not directory.is_dir():
        raise ValueError("Missing required directory: {}".format(directory))
    if is_reparse_point(directory):
        raise ValueError("Copy the actual directory before packaging; links are not accepted: {}".format(directory))
    def walk_error(error):
        raise error

    for current, subdirectories, filenames in os.walk(
            str(directory), followlinks=False, onerror=walk_error):
        subdirectories[:] = sorted(name for name in subdirectories if name not in SKIP_DIRECTORIES)
        for name in subdirectories:
            child = Path(current) / name
            if is_reparse_point(child):
                raise ValueError("Linked directory is not safe to package: {}".format(child))
        for name in sorted(filenames):
            path = Path(current) / name
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            if is_reparse_point(path):
                raise ValueError("Linked file is not safe to package: {}".format(path))
            yield path


def validated_files(root=ROOT):
    root = Path(root).resolve()
    required_files = (
        "backend/app/__init__.py", "backend/app/main.py", "backend/app/models.py",
        "backend/app/routers/datasource.py", "backend/app/routers/knowledge.py",
        "backend/app/routers/perspective.py", "backend/users.xlsx",
        "backend/requirements-win7.txt", "frontend/dist/index.html",
        "backend/projects/index.json", "backend/scripts/smoke_jsonl_import.py",
        "scripts/check_win7.py", "scripts/win7_launcher.py", "scripts/prepare_win7.py",
        "start_win7.bat", "Win7部署说明.md", "启动.txt",
        "win7-python.example.txt", "test.png",
    )
    for relative in required_files:
        require_file(root / relative, allow_empty=relative.endswith("/__init__.py"))
    requirements = read_requirements(root / "backend" / "requirements-win7.txt")
    hashes = check_wheels(root / "wheelhouse-win7", requirements)
    prerequisite_hashes = check_prerequisites(root / "prerequisites")
    hashes.update({"prerequisites/" + name: checksum
                   for name, checksum in prerequisite_hashes.items()})
    check_runtime(root / "CF37v2", requirements)

    # Read-only checks share the launcher's frontend validation without importing
    # it, any dependency packages, or the application itself.
    from html.parser import HTMLParser

    class Assets(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self)
            self.script_count = 0

        def handle_starttag(self, tag, attributes):
            attributes = dict(attributes)
            if tag == "script" and attributes.get("src"):
                self.script_count += 1
            reference = attributes.get("src") if tag == "script" else (
                attributes.get("href") if tag == "link" and
                "stylesheet" in attributes.get("rel", "").split() else None)
            if reference and not reference.startswith(("http://", "https://", "//", "data:")):
                asset = (root / "frontend" / "dist" /
                         reference.split("?", 1)[0].split("#", 1)[0].lstrip("/")).resolve()
                if (root / "frontend" / "dist").resolve() not in asset.parents:
                    raise ValueError("Frontend asset escapes dist: {}".format(reference))
                require_file(asset)

    assets = Assets()
    assets.feed((root / "frontend" / "dist" / "index.html").read_text(encoding="utf-8"))
    if not assets.script_count:
        raise ValueError("Built frontend index.html does not reference any JavaScript asset")
    directories = (
        "backend/app", "backend/projects", "backend/uploads", "backend/scripts",
        "backend/tests", "frontend/dist", "scripts", "CF37v2", "wheelhouse-win7",
        "prerequisites",
    )
    paths = set()
    for relative in directories:
        paths.update(files_in(root / relative))
    paths.update(root / relative for relative in (
        "backend/users.xlsx", "backend/requirements-win7.txt", "start_win7.bat",
        "Win7部署说明.md", "启动.txt", "win7-python.example.txt", "test.png"))
    return root, sorted(paths, key=lambda path: path.relative_to(root).as_posix()), hashes


def signature(path):
    information = path.stat()
    return information.st_size, information.st_mtime_ns


def write_archive(root, paths, hashes, output, force=False):
    if output.exists() and not force:
        raise ValueError("Output already exists. Use --force to replace it: {}".format(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".win7-package-", suffix=".zip.tmp",
                                                 dir=str(output.parent))
    os.close(descriptor)
    temporary = Path(temporary_name)
    snapshots = {path: signature(path) for path in paths}
    try:
        with zipfile.ZipFile(str(temporary), "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            archive.writestr(TOP_LEVEL + "/", b"")
            # Keep empty uploads/project directories in the extracted deployment.
            for relative in ("backend/projects", "backend/uploads"):
                archive.writestr(TOP_LEVEL + "/" + relative + "/", b"")
            for path in paths:
                if signature(path) != snapshots[path]:
                    raise ValueError("File changed during packaging: {}".format(path))
                relative = path.relative_to(root).as_posix()
                timestamp = time.localtime(path.stat().st_mtime)[:6]
                if timestamp[0] < 1980 or timestamp[0] > 2107:
                    timestamp = (1980, 1, 1, 0, 0, 0)
                information = zipfile.ZipInfo(TOP_LEVEL + "/" + relative, date_time=timestamp)
                information.compress_type = zipfile.ZIP_DEFLATED
                information.external_attr = 0o100644 << 16
                hash_key = path.name if relative.startswith("wheelhouse-win7/") else relative
                digest = hashlib.sha256() if hash_key in hashes else None
                with path.open("rb") as source, archive.open(information, "w", force_zip64=True) as destination:
                    for block in iter(lambda: source.read(CHUNK_SIZE), b""):
                        destination.write(block)
                        if digest is not None:
                            digest.update(block)
                if signature(path) != snapshots[path]:
                    raise ValueError("File changed while being archived: {}".format(path))
                if digest is not None and digest.hexdigest().lower() != hashes[hash_key].lower():
                    raise ValueError("Verified input changed since validation: {}".format(relative))
        if output.exists() and not force:
            raise ValueError("Output appeared during packaging; refusing to overwrite: {}".format(output))
        os.replace(str(temporary), str(output))
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Replace an existing offline ZIP")
    parser.add_argument("--check-only", action="store_true", help="Validate package inputs without writing a ZIP")
    args = parser.parse_args(argv)
    try:
        if OUTPUT.exists() and not args.force and not args.check_only:
            raise ValueError("Output already exists. Use --force to replace it: {}".format(OUTPUT))
        root, paths, hashes = validated_files()
        print("[OK] Validated {} files, {} verified offline wheels, runtime, OCR models and VC++ installer.".format(
            len(paths), sum(1 for name in hashes if name.endswith(".whl"))), flush=True)
        if args.check_only:
            return 0
        write_archive(root, paths, hashes, OUTPUT, force=args.force)
        print("[OK] Offline ZIP: {}".format(OUTPUT), flush=True)
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        print("[ERROR] Packaging refused: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
