"""Opt-in R10 real Chromium integration: python -B tests/browser_smoke_r10.py.

Uses the real revamped controller, persistence, deployment and launcher. Only
the destination and diagnostic flags are changed at the process boundary:
Discord is replaced by local fixtures (including a recording HTTP proxy).
No credentials, Discord navigation, or existing profiles are used. Evidence
and disposable profiles are retained below repository tmp/ for inspection.
The optional websocket-client package is used only by this diagnostic script.
"""

from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

import psutil
import websocket


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from revamped.extensions import REQUIRED_EXTENSION_NAMES
from revamped.environment import environment_runtime_notes
from revamped.launcher import DISCORD_URL
from revamped.main import compose


PAGE = b"<!doctype html><html><head><title>R10 local fixture</title></head><body>R10 disposable fixture</body></html>"


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if "/r10-fixture" in self.path:
            self.server.requests.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        try:
            self.wfile.write(PAGE)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def do_CONNECT(self):
        # Never forward background traffic from this diagnostic browser.
        self.send_error(502, "Local fixture proxy does not forward traffic")

    def log_message(self, *args):
        pass


class CDP:
    def __init__(self, address):
        self.socket = websocket.create_connection(address, timeout=10, suppress_origin=True)
        self.next_id = 0

    def call(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        self.socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == request_id:
                if "error" in message:
                    raise AssertionError(f"{method}: {message['error']}")
                return message.get("result", {})

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
        })
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result["result"].get("value")

    def close(self):
        self.socket.close()


def inventory(root):
    return {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def stop_own_browser(process):
    if process.poll() is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            child.terminate()
        parent.terminate()
        _, alive = psutil.wait_procs([parent, *children], timeout=5)
        for owned in alive:
            owned.kill()
        process.wait(timeout=10)
    except psutil.NoSuchProcess:
        pass


def main():
    temporary_root = PROJECT_ROOT / "tmp"
    temporary_root.mkdir(exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="r10 real runtime ", dir=temporary_root)).resolve()
    assert workspace != temporary_root.resolve() and workspace.is_relative_to(temporary_root.resolve())
    source_before = inventory(PROJECT_ROOT / "extensions")
    legacy_before = sha256((PROJECT_ROOT / "legacy/profile_manager.py").read_bytes()).hexdigest()
    root_main_before = sha256((PROJECT_ROOT / "main.py").read_bytes()).hexdigest()
    servers = []
    for _ in range(2):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        server.requests = []
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
    direct, proxy = servers
    records = []
    spawned = []
    report = {"workspace": str(workspace), "launches": records}

    def launch_case(label, profile_id, destination):
        captured = {}

        def real_factory(command, **kwargs):
            captured["generated_command"] = list(command)
            actual = [arg for arg in command if arg != DISCORD_URL]
            actual += [
                "--headless=new", "--disable-gpu", "--disable-background-networking",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                destination,
            ]
            diagnostic = workspace / f"{profile_id}-chromium-stderr.txt"
            with diagnostic.open("wb") as diagnostics:
                kwargs["stderr"] = diagnostics
                process = subprocess.Popen(actual, **kwargs)
            spawned.append(process)
            captured["process"] = process
            captured["executed_command"] = actual
            return process

        # New composition proves saved settings are consumed after manager restart.
        application = compose(workspace, process_factory=real_factory)
        captured["environment_notes"] = environment_runtime_notes(application.profile_service.get_profile_record(profile_id))
        application.controller.refresh()
        application.controller.set_selection([profile_id])
        result = application.controller.open_selected()
        assert result == {"requested": 1, "running": 0, "errors": []}, result
        process = captured.pop("process")
        captured["label"] = label
        records.append(captured)
        profile = application.profile_service.require_profile_dir(profile_id)
        active_port = profile / "DevToolsActivePort"
        browser = page = extension_page = None
        try:
            deadline = time.monotonic() + 25
            while not active_port.is_file():
                assert process.poll() is None, "Chromium exited during startup"
                if time.monotonic() > deadline:
                    raise AssertionError("Chromium did not expose its local diagnostic endpoint")
                time.sleep(0.1)
            port, browser_path = active_port.read_text().splitlines()[:2]
            base = f"http://127.0.0.1:{port}"
            browser = CDP(f"ws://127.0.0.1:{port}{browser_path}")
            version = browser.call("Browser.getVersion")
            captured["browser_version"] = version["product"]
            captured["actual_process_command"] = psutil.Process(process.pid).cmdline()
            for argument in captured["generated_command"]:
                if argument != DISCORD_URL:
                    assert argument in captured["actual_process_command"], argument
            while True:
                with urlopen(base + "/json/list", timeout=3) as response:
                    targets = json.load(response)
                candidates = [target for target in targets
                              if target.get("type") == "page" and "/r10-fixture" in target.get("url", "")]
                if candidates:
                    page = CDP(candidates[0]["webSocketDebuggerUrl"])
                    if page.evaluate("document.title") == "R10 local fixture":
                        break
                    page.close()
                    page = None
                if time.monotonic() > deadline:
                    raise AssertionError("Fixture navigation did not finish")
                time.sleep(0.1)
            captured["runtime_environment"] = page.evaluate("""({
                outerWidth, outerHeight, innerWidth, innerHeight,
                devicePixelRatio, language: navigator.language,
                userAgent: navigator.userAgent, maxTouchPoints: navigator.maxTouchPoints,
                touchEvents: 'ontouchstart' in window,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
            })""")
            target_id = browser.call("Target.createTarget", {"url": "chrome://extensions/"})["targetId"]
            extension_page = CDP(f"ws://127.0.0.1:{port}/devtools/page/{target_id}")
            while extension_page.evaluate("typeof chrome.developerPrivate") == "undefined":
                if time.monotonic() > deadline:
                    raise AssertionError("chrome://extensions did not initialize")
                time.sleep(0.1)
            captured["runtime_extensions"] = extension_page.evaluate("""new Promise(resolve =>
                chrome.developerPrivate.getExtensionsInfo({includeDisabled: true, includeTerminated: true},
                entries => resolve(entries.map(e => ({id: e.id, name: e.name, state: e.state,
                    path: e.path, manifestErrors: e.manifestErrors, runtimeErrors: e.runtimeErrors}))))
            )""")
            required_labels = {"Discord Autofill", "Discord Token Extractor"}
            enabled = {entry["name"] for entry in captured["runtime_extensions"] if entry["state"] == "ENABLED"}
            assert required_labels.issubset(enabled), captured["runtime_extensions"]
            load_switch = next(arg for arg in captured["generated_command"] if arg.startswith("--load-extension="))
            paths = load_switch.split("=", 1)[1].split(",")
            assert {Path(path).name for path in paths} == set(REQUIRED_EXTENSION_NAMES)
            for path in paths:
                assert Path(path).resolve().is_relative_to(workspace)
                manifest = json.loads((Path(path) / "manifest.json").read_text(encoding="utf-8"))
                assert manifest["manifest_version"] == 3
            assert application.account_service.get_account(profile_id) is None
            print(f"PASS: {label}; real process arguments and both enabled extensions verified", flush=True)
        finally:
            for connection in (extension_page, page, browser):
                if connection is not None:
                    connection.close()
            stop_own_browser(process)
            deadline = time.monotonic() + 10
            while application.process_inspector.using_directory(profile):
                if time.monotonic() > deadline:
                    raise AssertionError("Owned Chromium processes remained active")
                time.sleep(0.1)
            if active_port.exists():
                active_port.unlink()
        return captured

    try:
        application = compose(workspace)
        application.profile_service.initialize_metadata()
        controller = application.controller
        desktop = controller.create_profile("R10 Desktop Off")
        controller.save_environment("desktop")
        controller.save_proxy(False)
        mobile = controller.create_profile("R10 Mobile Off")
        controller.save_environment("mobile")
        controller.save_proxy(False)
        custom = controller.create_profile("R10 Custom Proxy")
        controller.save_environment("custom", {
            "viewport_width": 1000, "viewport_height": 700,
            "device_scale_factor": 1.25, "language": "fr-FR",
            "touch_mode": True, "mobile_mode": False, "timezone": "UTC",
        })
        controller.save_proxy(True, "http", "127.0.0.1", proxy.server_port)
        direct_url = f"http://127.0.0.1:{direct.server_port}/r10-fixture"
        desktop_result = launch_case("Desktop / Proxy Off", desktop, direct_url)
        mobile_result = launch_case("Mobile / Proxy Off", mobile, direct_url)
        proxy_result = launch_case("Custom / HTTP Proxy", custom, "http://r10-proxy.invalid/r10-fixture")
        assert any(path.startswith("http://r10-proxy.invalid/r10-fixture") for path in proxy.requests), proxy.requests
        assert f"--proxy-server=http://127.0.0.1:{proxy.server_port}" in proxy_result["actual_process_command"]
        assert proxy_result["runtime_environment"]["devicePixelRatio"] == 1.25
        assert proxy_result["runtime_environment"]["language"] == "fr-FR"
        assert proxy_result["runtime_environment"]["touchEvents"] is True
        assert mobile_result["runtime_environment"]["touchEvents"] is True
        assert desktop_result["runtime_environment"]["touchEvents"] is False
        assert mobile_result["runtime_environment"]["userAgent"] == desktop_result["runtime_environment"]["userAgent"]
        assert mobile_result["runtime_environment"]["outerWidth"] != desktop_result["runtime_environment"]["outerWidth"]
        controller.refresh()
        controller.set_selection([custom])
        controller.save_proxy(False)
        off_result = launch_case("Custom / Proxy Off after restart", custom, direct_url)
        assert not any(arg.startswith("--proxy-") for arg in off_result["generated_command"])
        assert not any(arg.startswith("--proxy-") for arg in off_result["actual_process_command"])
        assert inventory(PROJECT_ROOT / "extensions") == source_before
        assert sha256((PROJECT_ROOT / "legacy/profile_manager.py").read_bytes()).hexdigest() == legacy_before
        assert sha256((PROJECT_ROOT / "main.py").read_bytes()).hexdigest() == root_main_before
        report["proxy_fixture_requests"] = proxy.requests
        report["direct_fixture_requests"] = direct.requests
        report["result"] = "PASS"
        print("PASS: recording proxy received traffic; Proxy Off has no switch; runtime environment differs", flush=True)
        print("PASS: repository extension sources, legacy and root main remain unchanged", flush=True)
    except Exception as error:
        report["result"] = "FAIL"
        report["error"] = str(error)
        raise
    finally:
        for process in spawned:
            stop_own_browser(process)
        for server in servers:
            server.shutdown()
            server.server_close()
        evidence = workspace / "r10-runtime-evidence.json"
        evidence.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Runtime evidence and disposable profiles retained: {evidence}", flush=True)


if __name__ == "__main__":
    main()
