"""Opt-in real Chromium smoke test: python -B tests/browser_smoke_m2.py.

Uses only a loopback fixture page and disposable data under workspace tmp/.
No real accounts, extension code, or existing profile directories are used.
"""

from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse
import uuid
from unittest.mock import Mock, patch

from test_m1_runtime import PROJECT_ROOT, load_manager


PAGE = b'''<!doctype html><html><body><div id="result">waiting</div><script>
const run = new URL(location.href).searchParams.get('run');
const barrier = new Image();
barrier.src = '/hold?run=' + run;
document.body.appendChild(barrier);
(async () => {
  const marker = new URL(location.href).searchParams.get('write');
  const database = await new Promise((resolve, reject) => {
    const request = indexedDB.open('m2-fixture', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('markers');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  if (marker !== null) {
    localStorage.setItem('m2-marker', marker);
    document.cookie = 'm2_marker=' + marker + '; Max-Age=86400; Path=/';
    await new Promise((resolve, reject) => {
      const tx = database.transaction('markers', 'readwrite');
      tx.objectStore('markers').put(marker, 'value');
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }
  const stored = await new Promise((resolve, reject) => {
    const request = database.transaction('markers').objectStore('markers').get('value');
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
  database.close();
  document.getElementById('result').textContent = 'RESULT:' + JSON.stringify({
    local: localStorage.getItem('m2-marker'), cookie: document.cookie, indexed: stored
  });
})().catch(() => document.getElementById('result').textContent = 'FIXTURE_ERROR')
    .finally(() => fetch('/done?run=' + run));
</script></body></html>'''


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        request = urlparse(self.path)
        run = parse_qs(request.query).get('run', [''])[0]
        if request.path in ('/hold', '/done'):
            event = self.server.events.setdefault(run, threading.Event())
            if request.path == '/hold':
                event.wait(15)
            else:
                event.set()
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(PAGE)))
        self.end_headers()
        try:
            self.wfile.write(PAGE)
        except (BrokenPipeError, ConnectionAbortedError):
            # Chromium can cancel a navigation after the storage fixture has
            # completed; that is not a smoke-test failure.
            pass

    def log_message(self, *args):
        pass


def runtime_inventory():
    return {path.relative_to(PROJECT_ROOT): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in (PROJECT_ROOT / 'browser').rglob('*') if path.is_file()}


def main():
    module = load_manager()
    if not module.BROWSER_EXE.is_file():
        raise RuntimeError(f'Runtime required: {module.BROWSER_EXE}')
    before_runtime = runtime_inventory()
    real_state = PROJECT_ROOT / 'legacy/data/Local State'
    before_state = real_state.read_bytes() if real_state.exists() else None
    temp_root = PROJECT_ROOT / 'tmp'
    temp_root.mkdir(exist_ok=True)
    # Retain the disposable directory on failure for inspection; clean only on success.
    work = Path(tempfile.mkdtemp(prefix='m2 smoke Thử ', dir=temp_root)).resolve()
    server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
    server.events = {}
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    spawned = []
    succeeded = False
    real_popen = subprocess.Popen
    try:
        with ExitStack() as stack:
            data = work / 'legacy/data'
            stack.enter_context(patch.object(module, 'DATA_DIR', data))
            stack.enter_context(patch.object(module, 'LOCAL_STATE', data / 'Local State'))
            profiles = module.ProfileManager()
            first = profiles.create_profile('M2 smoke A')
            second = profiles.create_profile('M2 smoke B')
            address = f'http://127.0.0.1:{server.server_port}/'

            def run_batch(writes):
                batch = []
                def launch(command, **kwargs):
                    root_arg = next(arg.split('=', 1)[1] for arg in command if arg.startswith('--user-data-dir='))
                    pid = Path(root_arg).name
                    url = address + '?run=' + uuid.uuid4().hex
                    if writes[pid] is not None:
                        url += '&write=' + writes[pid]
                    command = [arg for arg in command if arg != 'https://discord.com/app']
                    command += ['--headless=new', '--disable-gpu', '--disable-background-networking',
                                '--dump-dom', url]
                    kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    process = real_popen(command, **kwargs)
                    batch.append((pid, process))
                    spawned.append(process)
                    return process

                # A fresh launcher/manager for every batch simulates manager restart.
                app = module.ProfileManagerApp.__new__(module.ProfileManagerApp)
                app.get_selected_profiles = Mock(return_value=[(pid, pid) for pid in writes])
                app.profile_manager = module.ProfileManager()
                app.launcher = module.ChromiumLauncher()
                app.update_status = Mock()
                with patch.object(module.subprocess, 'Popen', side_effect=launch), \
                        patch.object(module.messagebox, 'showerror') as error:
                    app.open_discord()
                if error.called:
                    raise AssertionError(error.call_args.args[1])
                assert len(batch) == len(writes), 'A profile was unexpectedly considered already running'
                results = {}
                for pid, process in batch:
                    output, diagnostics = process.communicate(timeout=30)
                    assert process.returncode == 0, (
                        f'Chromium exited with code {process.returncode}: '
                        + diagnostics.decode('utf-8', errors='replace')[-3000:]
                    )
                    match = re.search(r'RESULT:(\{[^<]+\})', output.decode('utf-8', errors='replace'))
                    assert match, 'Fixture page did not complete storage operations'
                    results[pid] = json.loads(html.unescape(match.group(1)))
                deadline = time.monotonic() + 10
                while any(module.browser_using_directory(data / pid) for pid in writes):
                    if time.monotonic() > deadline:
                        raise AssertionError('Chromium children remained active after shutdown')
                    time.sleep(0.1)
                return results

            initial = run_batch({first: None, second: None})
            assert all(row == {'local': None, 'cookie': '', 'indexed': None} for row in initial.values())
            print('PASS: two fresh profiles open concurrently with empty isolated storage', flush=True)
            written = run_batch({first: 'alpha', second: 'bravo'})
            expected = {
                first: {'local': 'alpha', 'cookie': 'm2_marker=alpha', 'indexed': 'alpha'},
                second: {'local': 'bravo', 'cookie': 'm2_marker=bravo', 'indexed': 'bravo'},
            }
            assert written == expected
            print('PASS: separate cookies, Local Storage, and IndexedDB in both profiles', flush=True)
            profiles.rename_profile(first, 'M2 smoke renamed')
            assert run_batch({first: None, second: None}) == expected
            print('PASS: browser/manager restart and rename retain each profile\'s data', flush=True)
            profiles.delete_profile(second)
            assert run_batch({first: None}) == {first: expected[first]}
            print('PASS: deleting one closed profile preserves the other profile', flush=True)
            assert runtime_inventory() == before_runtime
            assert (real_state.read_bytes() if real_state.exists() else None) == before_state
            print('PASS: runtime inventory and existing application metadata remain unchanged', flush=True)
            succeeded = True
    finally:
        for process in spawned:
            if process.poll() is None:
                # Only processes created by this test are eligible for termination.
                try:
                    children = module.psutil.Process(process.pid).children(recursive=True)
                    for child in children:
                        child.terminate()
                    process.kill()
                    process.wait(timeout=10)
                    module.psutil.wait_procs(children, timeout=5)
                except (module.psutil.Error, OSError, subprocess.TimeoutExpired):
                    pass
        server.shutdown()
        server.server_close()
        if succeeded:
            import shutil
            assert work.is_relative_to(temp_root.resolve()) and work != temp_root.resolve()
            shutil.rmtree(work)
        else:
            print(f'Disposable smoke-test data retained at: {work}', flush=True)


if __name__ == '__main__':
    main()
