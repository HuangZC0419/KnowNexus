"""Run the existing FastAPI app and built frontend on one loopback port."""

from __future__ import print_function

import argparse
import importlib
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser

from check_win7 import ROOT, check_environment, report


def reserve_port(first=8000, last=8100):
    """Keep the selected socket open, avoiding port-check/startup races."""
    for port in range(first, last + 1):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            return listener, port
        except OSError:
            listener.close()
    raise RuntimeError("No available loopback port in {}-{}; no process was stopped.".format(first, last))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check files, dependencies and RapidOCR, then exit")
    parser.add_argument("--no-browser", action="store_true", help="Run without opening a browser")
    args = parser.parse_args(argv)
    if not check_environment(initialize_ocr=args.check):
        return 1
    if args.check:
        return 0

    # SSL DLLs must be discoverable before urllib imports http.client/ssl.
    from urllib.request import ProxyHandler, build_opener

    listener = None
    try:
        # app.main uses backend as its module root. Its normal startup behavior is
        # intentionally kept out of --check because it may initialize project data.
        os.chdir(str(ROOT / "backend"))
        sys.path.insert(0, str(ROOT / "backend"))
        report("[INFO] Loading the application and initializing RapidOCR...")
        module = importlib.import_module("app.main")
        if getattr(module, "ocr_engine", None) is None:
            raise RuntimeError("Application OCR engine was not initialized")
        import uvicorn
        listener, port = reserve_port()
        url = "http://127.0.0.1:{}/".format(port)
        expected_index = (ROOT / "frontend" / "dist" / "index.html").read_bytes()
        config = uvicorn.Config(module.app, host="127.0.0.1", port=port,
                                loop="asyncio", http="h11", log_level="info", use_colors=False)
        server = uvicorn.Server(config)
        status = {"ready": False, "error": None}
        finished = threading.Event()

        def open_when_ready():
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 90
            while not finished.is_set() and time.monotonic() < deadline:
                if server.should_exit:
                    return
                if server.started:
                    try:
                        with opener.open(url, timeout=2) as response:
                            content = response.read(len(expected_index) + 1)
                            ready = response.status == 200 and content == expected_index
                        if ready:
                            status["ready"] = True
                            report("[OK] Ready: " + url)
                            report("Keep this window open. Press Ctrl+C to stop the application.")
                            if not args.no_browser:
                                try:
                                    if not webbrowser.open(url, new=2):
                                        report("[INFO] Browser did not open automatically; open the URL above.")
                                except Exception as error:
                                    report("[INFO] Browser could not open: {}. Open the URL above.".format(error))
                            return
                    except Exception:
                        pass
                finished.wait(0.25)
            if not finished.is_set():
                status["error"] = "HTTP readiness timed out after 90 seconds; startup failed."
                report("[ERROR] " + status["error"])
                server.should_exit = True

        watcher = threading.Thread(target=open_when_ready, name="browser-readiness", daemon=True)
        watcher.start()
        try:
            server.run(sockets=[listener])
        finally:
            finished.set()
            watcher.join(timeout=3)
        if status["error"]:
            return 1
        if not status["ready"]:
            report("[ERROR] Server stopped before HTTP readiness; startup was not completed.")
            return 1
        return 0
    except KeyboardInterrupt:
        report("Application stopped.")
        return 0
    except Exception:
        report("[ERROR] Application startup failed (full error follows).")
        traceback.print_exc()
        return 1
    finally:
        if listener is not None:
            listener.close()


if __name__ == "__main__":
    sys.exit(main())
