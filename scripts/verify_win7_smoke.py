r"""Manually verify deployment in an isolated project copy, never in live data.

Usage: CF37v2\python.exe -B scripts\verify_win7_smoke.py
The script retains its copy, server log and report in .win7-validation.
It launches and stops only its own win7_launcher.py child process.
"""

from __future__ import print_function

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
from urllib.parse import urlencode, urljoin, urlsplit
import uuid


ROOT = Path(__file__).resolve().parent.parent


def runtime_environment(runtime):
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join([
        str(runtime), str(runtime / "Library" / "bin"),
        str(runtime / "Scripts"), environment.get("PATH", ""),
    ])
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment.update(PYTHONUTF8="1", PYTHONNOUSERSITE="1",
                       PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    return environment


def data_hashes(root):
    """Include file names to detect created/deleted files as well as edits."""
    backend = root / "backend"
    files = [backend / "users.xlsx", backend / "data.json"]
    for name in ("projects", "uploads"):
        directory = backend / name
        if directory.is_dir():
            files.extend(path for path in directory.rglob("*") if path.is_file())
    result = {}
    for path in sorted(set(files)):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[str(path.relative_to(root))] = digest.hexdigest()
    return result


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def make_project_copy(target):
    """Copy code/assets and the login workbook; create synthetic graph data."""
    backend = target / "backend"
    backend.mkdir(parents=True)
    shutil.copytree(str(ROOT / "backend" / "app"), str(backend / "app"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(str(ROOT / "backend" / "users.xlsx"), str(backend / "users.xlsx"))
    shutil.copytree(str(ROOT / "frontend" / "dist"), str(target / "frontend" / "dist"))
    shutil.copy2(str(ROOT / "test.png"), str(target / "test.png"))
    (target / "scripts").mkdir()
    for name in ("check_win7.py", "win7_launcher.py"):
        shutil.copy2(str(ROOT / "scripts" / name), str(target / "scripts" / name))
    (backend / "projects").mkdir()
    project_id = str(uuid.uuid4())
    write_json(backend / "projects" / "index.json", [{
        "id": project_id, "name": "Isolated validation seed",
        "created_at": "2000-01-01T00:00:00", "updated_at": "2000-01-01T00:00:00",
    }])
    graph = {
        "nodes": [
            {"id": "seed-a", "name": "Validation A", "x": 0, "y": 0},
            {"id": "seed-b", "name": "Validation B", "x": 240, "y": 0},
        ],
        "edges": [{"id": "seed-edge", "source": "seed-a", "target": "seed-b",
                   "relation": "validation", "kind": "relation"}],
    }
    write_json(backend / "projects" / (project_id + ".json"), graph)
    return project_id


class Assets(HTMLParser):
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


class Client:
    def __init__(self, base):
        # urllib.request imports ssl; defer it until the Conda DLL PATH is set.
        from urllib.request import ProxyHandler, build_opener
        self.base = base
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, method="GET", payload=None, headers=None, expected=200,
                timeout=90):
        from urllib.error import HTTPError
        from urllib.request import Request
        request = Request(urljoin(self.base, path), data=payload,
                          headers=headers or {}, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                status, body = response.status, response.read()
        except HTTPError as error:
            status, body = error.code, error.read()
        if status != expected:
            # Never include response bodies: authentication responses may contain secrets.
            raise AssertionError("{} {} returned HTTP {}; expected {}".format(
                method, path.split("?", 1)[0], status, expected))
        return body

    def json(self, path, method="GET", value=None, expected=200):
        payload = None if value is None else json.dumps(value).encode("utf-8")
        body = self.request(path, method, payload,
                            {"Content-Type": "application/json"}, expected)
        return json.loads(body.decode("utf-8")) if body else None

    def upload(self, path, name, content, expected=200):
        boundary = "----validation" + uuid.uuid4().hex
        prefix = ('--{}\r\nContent-Disposition: form-data; name="file"; '
                  'filename="{}"\r\nContent-Type: application/octet-stream\r\n\r\n'
                  .format(boundary, name)).encode("utf-8")
        payload = prefix + content + ("\r\n--{}--\r\n".format(boundary)).encode("ascii")
        body = self.request(path, "POST", payload,
                            {"Content-Type": "multipart/form-data; boundary=" + boundary},
                            expected)
        return json.loads(body.decode("utf-8"))


def first_login(workbook_path):
    import openpyxl
    workbook = openpyxl.load_workbook(str(workbook_path), read_only=True, data_only=True)
    try:
        for row in workbook.active.iter_rows(min_row=2, values_only=True):
            if row[0] and row[1]:
                password = str(int(row[1])) if isinstance(row[1], (int, float)) else str(row[1]).strip()
                return {"username": str(row[0]).strip(), "password": password}
    finally:
        workbook.close()
    raise AssertionError("No usable login account in the copied workbook")


def wait_ready(process, log_path, deadline):
    """Use the child's advertised URL; never attach to an unrelated local server."""
    while time.monotonic() < deadline:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"\[OK\] Ready: (http://127\.0\.0\.1:\d+/)", content)
        if match:
            if process.poll() is not None:
                raise RuntimeError("The validation server exited after reporting readiness")
            return match.group(1)
        if process.poll() is not None:
            raise RuntimeError("The validation server exited; inspect server.log")
        time.sleep(0.25)
    raise RuntimeError("The validation server was not ready within 90 seconds")


def check_http(client, target, project_id, completed):
    def passed(name):
        completed.append(name)
        print("[OK] " + name, flush=True)

    index = client.request("/")
    if index != (target / "frontend" / "dist" / "index.html").read_bytes():
        raise AssertionError("HTTP index does not match the isolated frontend build")
    parser = Assets()
    parser.feed(index.decode("utf-8"))
    assets = [path for path in parser.paths if not urlsplit(path).netloc]
    if not assets:
        raise AssertionError("No local built JavaScript/CSS assets in index.html")
    frontend = (target / "frontend" / "dist").resolve()
    for path in assets:
        local = (frontend / urlsplit(path).path.lstrip("/")).resolve()
        if frontend not in local.parents or client.request(path) != local.read_bytes():
            raise AssertionError("Static asset does not match the isolated frontend build")
    passed("HTML and {} built static assets".format(len(assets)))

    diagnostic = client.request("/connection-check.html")
    if diagnostic != (frontend / "connection-check.html").read_bytes():
        raise AssertionError("HTTP diagnostic page does not match the isolated frontend build")
    passed("Standalone connection diagnostic page")

    invalid_login = client.json("/api/auth/login", "POST", {}, 422)
    if not isinstance(invalid_login, dict) or not invalid_login.get("detail"):
        raise AssertionError("Empty login payload did not return nonempty JSON detail")
    passed("Empty login payload returns HTTP 422 and nonempty JSON detail")

    schema = client.json("/openapi.json")
    for path in ("/api/projects", "/api/graph", "/api/auth/login", "/api/ocr/extract",
                 "/api/datasource/file/upload", "/api/datasource/jsonl/import"):
        if path not in schema.get("paths", {}):
            raise AssertionError("OpenAPI route missing: " + path)
    passed("OpenAPI schema and routes")

    projects = client.json("/api/projects")
    if not any(project["id"] == project_id for project in projects):
        raise AssertionError("Synthetic seed project missing")
    graph = client.json("/api/graph?" + urlencode({"project_id": project_id}))
    if len(graph.get("nodes", [])) != 2 or len(graph.get("edges", [])) != 1:
        raise AssertionError("Seed graph was not loaded correctly")
    created = client.json("/api/projects", "POST", {"name": "Disposable smoke project"}, 201)
    test_id = created["id"]
    graph_path = "/api/graph?" + urlencode({"project_id": test_id})
    if client.json(graph_path).get("nodes"):
        raise AssertionError("New test project should have an empty graph")
    passed("Project creation and graph loading")

    credentials = first_login(target / "backend" / "users.xlsx")
    login = client.json("/api/auth/login", "POST", credentials)
    del credentials
    if not login.get("success") or not login.get("token"):
        raise AssertionError("Login with the copied workbook failed")
    # Do not put session tokens in URLs: the server's access log records queries.
    del login
    passed("Workbook login (credentials hidden)")

    ocr = client.upload("/api/ocr/extract", "test.png", (target / "test.png").read_bytes())
    if not str(ocr.get("raw_text", "")).strip():
        raise AssertionError("OCR returned no recognized text for test.png")
    passed("Image OCR recognized nonempty text")

    sample = {
        "file_name": "validation.pdf",
        "spans": [{"id": 1, "text": "实体甲", "label": "参数"},
                  {"id": 2, "text": "实体乙", "label": "工序"}],
        "relations": [{"fromId": 1, "toId": 2, "type": "关联"}],
    }
    uploaded = client.upload("/api/datasource/file/upload", "中文验证.jsonl",
                             (json.dumps(sample, ensure_ascii=False) + "\n").encode("utf-8"))
    if uploaded.get("file_name") != "中文验证.jsonl":
        raise AssertionError("UTF-8 multipart file name was not preserved")
    summary = uploaded.get("jsonl_summary", {})
    if summary.get("entities") != 2 or summary.get("relations") != 1:
        raise AssertionError("JSONL upload summary was incorrect")
    imported = client.json("/api/datasource/jsonl/import", "POST",
                           {"source_id": uploaded["file_id"]})
    if len(imported.get("nodes", [])) != 3 or len(imported.get("edges", [])) < 1:
        raise AssertionError("JSONL import returned an incomplete graph")
    persisted = {"nodes": imported["nodes"], "edges": imported["edges"]}
    client.json(graph_path, "PUT", persisted)
    if len(client.json(graph_path).get("nodes", [])) != 3:
        raise AssertionError("Imported JSONL graph was not persisted")
    passed("JSONL upload, Chinese filename, import and graph persistence")

    before = data_hashes(target)
    client.upload("/api/datasource/file/upload", "broken.xlsx", b"not an Excel file", 400)
    if data_hashes(target) != before:
        raise AssertionError("Failed Excel upload left files or modified project data")
    # 50,001 tiny valid records exercise the JSONL 413 cleanup branch on Python 3.7.
    client.upload("/api/datasource/file/upload", "too-many.jsonl", b"{}\n" * 50001, 413)
    if data_hashes(target) != before:
        raise AssertionError("Rejected JSONL upload left files or modified project data")
    client.json("/api/datasource/jsonl/import", "POST", {"source_id": "../users"}, 400)
    client.json("/api/datasource/jsonl/import", "POST", {"source_id": str(uuid.uuid4())}, 404)
    passed("Rejected Excel/JSONL upload cleanup and invalid source IDs")

    client.json("/api/projects/" + test_id, "PUT", {"name": "Renamed disposable project"})
    client.request("/api/projects/" + test_id, "DELETE", expected=204)
    if any(project["id"] == test_id for project in client.json("/api/projects")):
        raise AssertionError("Disposable project was not deleted")
    passed("Project rename and deletion inside the isolated copy")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, help="Explicit CF37v2 directory")
    args = parser.parse_args()
    candidates = [args.runtime] if args.runtime else [ROOT / "CF37v2", ROOT.parent / "CF37v2"]
    runtime = next((path.resolve() for path in candidates if path and (path / "python.exe").is_file()), None)
    if runtime is None:
        parser.error("Put CF37v2 inside/beside the project or provide --runtime.")
    environment = runtime_environment(runtime)
    interpreter = runtime / "python.exe"
    if Path(sys.executable).resolve() != interpreter.resolve():
        return subprocess.call([str(interpreter), "-B", str(Path(__file__).resolve())]
                               + sys.argv[1:], env=environment)
    if sys.version_info[:2] != (3, 7):
        parser.error("Run with the CF37v2 Python 3.7 interpreter.")
    # Apply native-DLL paths in this process before importing openpyxl, too.
    os.environ.update(environment)
    target = ROOT / ".win7-validation" / ("project-" + uuid.uuid4().hex)
    target.mkdir(parents=True)
    report = {"passed": [], "original_data_unchanged": False, "success": False}
    before = data_hashes(ROOT)
    write_json(target / "original-data-before.json", before)
    process = None
    log_file = None
    print("[INFO] Isolated project: " + str(target), flush=True)
    try:
        seed_id = make_project_copy(target)
        temporary = target / "tmp"
        temporary.mkdir()
        environment.update(TMP=str(temporary), TEMP=str(temporary))
        log_path = target / "server.log"
        log_file = log_path.open("wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen([
            str(interpreter), "-B", str(target / "scripts" / "win7_launcher.py"), "--no-browser",
        ], cwd=str(target), env=environment, stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=flags)
        base = wait_ready(process, log_path, time.monotonic() + 90)
        report["server_url"] = base
        check_http(Client(base), target, seed_id, report["passed"])
        report["success"] = True
    except Exception as error:
        report["error"] = "{}: {}".format(type(error).__name__, error)
        print("[FAIL] " + report["error"], flush=True)
        traceback.print_exc()
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if log_file is not None:
            log_file.close()
        after = data_hashes(ROOT)
        write_json(target / "original-data-after.json", after)
        report["original_data_unchanged"] = before == after
        if before != after:
            report["success"] = False
            report["error"] = "Original business data hashes changed during validation"
            print("[FAIL] " + report["error"], flush=True)
        else:
            print("[OK] Original business data hashes unchanged", flush=True)
        write_json(target / "report.json", report)
        print("[INFO] Report: " + str(target / "report.json"), flush=True)
        print("[INFO] Server log: " + str(target / "server.log"), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
