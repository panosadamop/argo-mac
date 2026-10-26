"""Failure lines in the real box, VM only (opt-in, not discovered: run this module by name).

run.sh <repo> tests.shoot_failures → the real Argo binary asks a fake `claude` (first on PATH) that fails each way,
over a white page and a dark desktop; prints the windows it opened and PNGs as base64 (the runner copies nothing back).
Asks go through the app's own `demo` hook; the idea pill needs one added line, in a scratch copy of the source.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''#!PYTHON
import json, os, subprocess, sys
a, mode = sys.argv[1:], os.environ.get('FAKE_CLAUDE_MODE', '')
if a[:2] == ['auth', 'status']:
    print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'subscriptionType': 'max'})); sys.exit(0)
if '-p' not in a: sys.exit(0)
if mode == 'old':
    print("error: unknown option '--effort'", file=sys.stderr); sys.exit(1)
sys.stdin.readline()
out = lambda j: print(json.dumps(j), flush=True)
errors = {'plan': 'You\u2019ve hit your weekly limit \u00b7 resets 3pm (America/Los_Angeles)', 'long': 'Prompt is too long', '429': 'API Error: 429 too many requests'}
if mode in errors:
    out({'type': 'result', 'is_error': True, 'result': errors[mode], 'total_cost_usd': 0}); sys.exit(1)
if mode == 'voice':
    cmd = os.environ['ARGO_RESOURCES_DIR'] + '/argo.py --set "voice" off'
    out({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': cmd}}]}})
    said = subprocess.run(['/bin/sh', '-c', cmd], capture_output=True, text=True).stdout.strip()
    out({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': said, 'is_error': False}]}})
    out({'type': 'result', 'is_error': False, 'result': said, 'total_cost_usd': 0.001}); sys.exit(0)
'''
TOOL = r'''import Cocoa
setvbuf(stdout, nil, _IONBF, 0)
let a = CommandLine.arguments
if a[1] == "wins" {
    let all = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []
    let rows: [[String: Any]] = all.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == Int32(a[2])! }.map {
        ["id": $0[kCGWindowNumber as String] ?? 0, "layer": $0[kCGWindowLayer as String] ?? 0, "bounds": $0[kCGWindowBounds as String] ?? [:]] }
    print(String(decoding: try! JSONSerialization.data(withJSONObject: rows), as: UTF8.self)); exit(0)
}
let nsapp = NSApplication.shared; nsapp.setActivationPolicy(.accessory)
let s = NSScreen.screens[0].frame, dark = a[2] == "dark"
let w = NSWindow(contentRect: s, styleMask: [.borderless], backing: .buffered, defer: false)
w.backgroundColor = dark ? NSColor(srgbRed: 0.11, green: 0.13, blue: 0.19, alpha: 1) : .white
let t = NSTextField(wrappingLabelWithString: String(repeating: "The quick brown fox jumps over the lazy dog while the committee reviews the quarterly figures and the draft budget. ", count: 80))
t.frame = NSRect(x: 60, y: 40, width: s.width - 120, height: s.height - 80); t.font = .systemFont(ofSize: 15)
t.textColor = dark ? NSColor(white: 0.8, alpha: 1) : NSColor(white: 0.12, alpha: 1)
w.contentView!.addSubview(t); w.orderFrontRegardless(); print("READY"); nsapp.run()
'''
CASES = [   # (n, fake mode, request, seconds after the box shows)
    (1, 'plan', 'what is the capital of France', (4, 8)),
    (2, 'long', 'summarize this whole thread', (4, 8)),
    (3, '429', 'what is the capital of France', (4, 8)),
    (4, 'old', 'what is the capital of France', (4, 8)),
    (5, 'voice', 'turn your voice off', (4, 8)),
    (6, 'idea', '', (2, 5)),
]


def swiftc(source, binary):
    built = subprocess.run(['swiftc', '-O', str(source), '-o', str(binary)], capture_output=True, text=True)
    if built.returncode: raise AssertionError(built.stderr[-4000:])


class FailureShots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        source = (ROOT / 'Argo.swift').read_text()
        end = 'NSApplication.shared.setActivationPolicy(.accessory)\nNSApplication.shared.run()'
        demo = 'DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { app.js("listen")'
        assert source.count(end) == 1 and source.count(demo) == 1
        # 5 s: on the 2-CPU VM the box's page may still be loading at 1.5 s, and a js() call before it loads is lost
        hook = 'if UserDefaults.standard.bool(forKey: "shotIdea") { DispatchQueue.main.asyncAfter(deadline: .now() + 5) { app.idea(0) } }\n'
        (cls.root / 'Argo.swift').write_text(source.replace(end, hook + end).replace(demo, demo.replace('1.5', '5')))
        swiftc(cls.root / 'Argo.swift', cls.root / 'Argo')
        (cls.root / 'tool.swift').write_text(TOOL); swiftc(cls.root / 'tool.swift', cls.root / 'tool')
        # argo.py puts ~/.local/bin before the caller's PATH (and the VM has a signed-out Claude there), so the fakes live in a scratch HOME.
        # osascript: the VM can't answer the System Events prompt, so the front-window read would wait out its 60 s timeout for the same ''.
        cls.home = cls.root / 'home'; bin_ = cls.home / '.local/bin'; bin_.mkdir(parents=True)
        (bin_ / 'claude').write_text(FAKE.replace('PYTHON', sys.executable)); (bin_ / 'claude').chmod(0o755)
        (bin_ / 'osascript').write_text('#!/bin/sh\nexit 0\n'); (bin_ / 'osascript').chmod(0o755)
        cls.path = f'{bin_}:{os.environ["PATH"]}'
        for shadow in ('/opt/homebrew/bin/claude', '/usr/local/bin/claude', '/opt/homebrew/bin/osascript', '/usr/local/bin/osascript'):
            if os.path.exists(shadow): print(f'WARNING {shadow} would shadow a fake', flush=True)
        check = subprocess.run(['/bin/sh', str(ROOT / 'argo.py'), '--check'], capture_output=True, text=True, timeout=60,
                               env={**os.environ, 'HOME': str(cls.home), 'PATH': cls.path, 'ARGO_DIR': str(cls.root)})
        assert json.loads(check.stdout)['ok'], check.stdout + check.stderr

    def wins(self, pid):
        out = subprocess.run([str(self.root / 'tool'), 'wins', str(pid)], capture_output=True, text=True, timeout=5).stdout
        return json.loads(out or '[]')

    def box(self, rows):   # the box and its pill: Argo's status-bar-level panels, not the menu-bar icon
        return [r for r in rows if r['layer'] >= 20 and r['bounds'].get('Y', 0) > 30 and r['bounds'].get('Height', 0) > 20]

    def capture(self, name, *args):
        png = self.root / name
        subprocess.run(['/usr/sbin/screencapture', '-x', *args, str(png)], check=True, timeout=10)
        print(f'SHOT {name} {base64.b64encode(png.read_bytes()).decode()}', flush=True)

    def shoot(self, n, mode, request, delays, look):
        state = self.root / f'state-{n}-{look}'; state.mkdir()
        (state / 'settings.json').write_text(json.dumps({'hideWhenSharing': False, 'screen': 'never', 'selection': False}))
        env = {**os.environ, 'HOME': str(self.home), 'PATH': self.path, 'ARGO_DIR': str(state), 'ARGO_RESOURCES_DIR': str(ROOT),
               'FAKE_CLAUDE_MODE': mode}
        back = subprocess.Popen([str(self.root / 'tool'), 'back', look], stdout=subprocess.PIPE, text=True)
        self.assertEqual(back.stdout.readline().strip(), 'READY')
        args = ['-onboarded', 'YES'] + (['-shotIdea', 'YES'] if mode == 'idea' else ['-demo', request])
        errors = (state / 'stderr.txt').open('w')   # a pipe would stay open in the app's helpers and hang the teardown
        app = subprocess.Popen([str(self.root / 'Argo'), *args], env=env, stdout=subprocess.DEVNULL, stderr=errors, text=True)
        try:
            deadline = time.monotonic() + 20
            while not self.box(self.wins(app.pid)) and time.monotonic() < deadline: time.sleep(.1)
            shown = time.monotonic()
            for i, delay in enumerate(delays):
                time.sleep(max(0, shown + delay - time.monotonic()))
                rows = self.wins(app.pid); frames = self.box(rows)
                print(f'WINDOWS {n} {look} +{delay}s {json.dumps(rows)}', flush=True)
                self.assertFalse([r for r in rows if r['layer'] == 0], 'a normal window (Setup) opened')
                if not frames: print(f'NOBOX {n} {look} +{delay}s', flush=True); continue
                b = [f['bounds'] for f in frames]
                x0, y0 = min(f['X'] for f in b) - 30, min(f['Y'] for f in b) - 30
                x1, y1 = max(f['X'] + f['Width'] for f in b) + 30, max(f['Y'] + f['Height'] for f in b) + 30
                self.capture(f'show-{n}-{look}-{i}.png', f'-R{int(x0)},{int(y0)},{int(x1 - x0)},{int(y1 - y0)}')   # over the backdrop
                self.capture(f'show-{n}-{look}-{i}-window.png', '-o', f'-l{frames[0]["id"]}')   # the box alone: nothing on top can hide a clipped line
            self.capture(f'screen-{n}-{look}.png')   # the whole screen: no Setup window beside the box
            log = state / 'log.jsonl'
            if log.exists(): print(f'LOG {n} {look} {log.read_text()[-1500:]}', flush=True)
            prefs = json.loads((state / 'settings.json').read_text())
            print(f'PREFS {n} {look} speak={prefs.get("speak")}', flush=True)
        finally:
            app.terminate(); back.terminate()
            try: app.wait(timeout=5)
            except subprocess.TimeoutExpired: app.kill(); app.wait()
            back.wait(timeout=5); back.stdout.close(); errors.close()
            subprocess.run(['pkill', '-f', f'{ROOT}/argo.py'])   # the worker has its own process group; a waiting card would outlive the app
            print(f'STDERR {n} {look} {(state / "stderr.txt").read_text()[-800:]!r}', flush=True)

    def test_shots(self):
        for n, mode, request, delays in CASES:
            for look in ('light', 'dark'):
                with self.subTest(n=n, look=look): self.shoot(n, mode, request, delays, look)


if __name__ == '__main__':
    unittest.main()
