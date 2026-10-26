"""Onboarding layout checks in an offscreen WKWebView: no app, window, or user settings."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''import Cocoa
import WebKit
// Loads argv[1] at argv[2]×argv[3] with a recording "ob" bridge, runs argv[4] as an async function body, prints {"result", "posts"}.
final class Harness: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    var posts: [Any] = []
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { posts.append(m.body) }
    func webView(_ view: WKWebView, didFinish navigation: WKNavigation!) {
        view.callAsyncJavaScript(CommandLine.arguments[4], arguments: [:], in: nil, in: .page) { r in
            switch r {
            case .success(let x):
                let out = try! JSONSerialization.data(withJSONObject: ["result": x ?? NSNull(), "posts": self.posts])
                print(String(data: out, encoding: .utf8)!); exit(0)
            case .failure(let e): print(e); exit(1)
            }
        }
    }
}
let app = NSApplication.shared
let harness = Harness(), cfg = WKWebViewConfiguration(), width = Double(CommandLine.arguments[2])!, height = Double(CommandLine.arguments[3])!
cfg.userContentController.add(harness, name: "ob")
let view = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: height), configuration: cfg)
view.navigationDelegate = harness
view.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 20) { print("timeout"); exit(3) }
app.run()
'''
EVERY_PAGE = '''
  const filler = ' Extra setup guidance that can wrap onto several lines on a small display.'.repeat(5);
  for (const id of ['list', 'own', 'yours']) {
    const list = document.getElementById(id);
    if (!list.children.length) list.innerHTML = Array.from({length: id === 'list' ? 7 : 4}, (_, i) =>
      `<div class="row"><div class="txt"><b>Permission ${i + 1}</b><span>Why this permission is needed.${filler}</span></div><button class="allow">Allow</button></div>`).join('');
  }
  document.querySelectorAll('p.sub, .txt span, .done-note').forEach(node => node.textContent += filler);
  const rows = [];
  for (const page of document.querySelectorAll('.page')) {
    document.querySelectorAll('.page').forEach(other => other.classList.toggle('on', other === page));
    page.inert = false;
    page.scrollTop = 0;
    page.scrollTop = page.scrollHeight;
    void page.offsetHeight;
    const frame = page.getBoundingClientRect();
    const actions = [...page.querySelectorAll(':scope > .bar2 button, :scope > button.btn')]
      .filter(button => !button.hidden && getComputedStyle(button).display !== 'none');
    rows.push({
      id: page.id,
      horizontal: page.scrollWidth <= page.clientWidth + 1,
      actions: actions.length,
      reachable: actions.every(button => {
        const rect = button.getBoundingClientRect();
        return rect.top >= frame.top - 1 && rect.bottom <= frame.bottom + 1;
      })
    });
  }
  const sheet = document.getElementById('prov');
  sheet.hidden = false;
  sheet.querySelector('p').textContent += filler;
  sheet.scrollTop = sheet.scrollHeight;
  void sheet.offsetHeight;
  const card = sheet.querySelector('.card').getBoundingClientRect(), frame = sheet.getBoundingClientRect();
  return JSON.stringify({rows, sheet: {
    horizontal: sheet.scrollWidth <= sheet.clientWidth + 1,
    reachable: card.left >= frame.left - 1 && card.right <= frame.right + 1 &&
      sheet.querySelector('.acts').getBoundingClientRect().bottom <= frame.bottom + 1
  }});
'''
# The real page script with live status sent in like Onboarding.push/checkPlan, then every row is scrolled to and clicked like a user would.
PERMISSION_ROWS = '''
  const tick = ms => new Promise(r => setTimeout(r, ms));
  while (!window.ob) await tick(10);
  const $ = id => document.getElementById(id), on = GRANTED;
  ob.plan(on ? {ok: true, need: '', client: 'claude', text: 'Ready with your Claude plan.'} : {ok: false, need: 'login', client: 'claude', text: 'Sign in to Claude Code to use your plan.'});
  ob.set(Object.fromEntries(['mic', 'speech', 'ax', 'screen', 'auto', 'calendar', 'tools', 'chrome'].map(k => [k, on])));
  ob.connectors(on ? {connected: ['Gmail', 'Drive'], signin: []} : {connected: [], signin: ['Notion']});
  const reveal = (el, page) => {   // scroll the page only: an overflow:hidden list is not something a user can scroll
    const r = el.getBoundingClientRect(), f = page.getBoundingClientRect();
    page.scrollTop += r.top - f.top - (f.height - r.height) / 2; void page.offsetHeight;
  };
  const inside = (el, box) => { const r = el.getBoundingClientRect(), f = box.getBoundingClientRect(); return r.top >= f.top - 1 && r.bottom <= f.bottom + 1 && r.left >= f.left - 1 && r.right <= f.right + 1; };
  const hit = (el, page) => {
    reveal(el, page);
    const r = el.getBoundingClientRect(), h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return h && el.contains(h) ? h : null;
  };
  const tap = (el, page) => { const h = hit(el, page); h?.click(); return !!h; };
  const rows = page => [...$(page).querySelectorAll('.row')].map(row => {
    const list = row.parentElement, allow = row.querySelector('.allow'), shows = getComputedStyle(allow).display !== 'none';
    reveal(row, $(page));
    return {page, id: row.id, inList: inside(row, list), onPage: inside(row, $(page)),
      why: !!hit(row.querySelector('.txt span'), $(page)), name: !!hit(row.querySelector('.txt b'), $(page)),
      check: row.classList.contains('ok') && !shows && !!hit(row.querySelector('.check'), $(page)), allow: shows && tap(allow, $(page)) && allow.dataset.id};
  });
  const out = [], stuck = error => JSON.stringify({error});
  if (!tap(document.querySelector('#welcome [data-go="perms"]'), $('welcome'))) return stuck('Get Started is unreachable');
  out.push(...rows('perms'));
  if (!tap($('next'), $('perms')) || !$('agents').classList.contains('on')) return stuck('perms has no reachable way on');
  out.push(...rows('agents'));
  if (!tap($('agents-next'), $('agents')) || !$('try').classList.contains('on')) return stuck('agents has no reachable way on');
  return JSON.stringify(out);
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class OnboardingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        html = (ROOT / 'ui/onboarding.html').read_text()
        cls.page = Path(cls.tmp.name) / 'onboarding.html'
        cls.page.write_text(re.sub(r'<script\b.*?</script>', '', html, flags=re.S))
        still = '<style>*,*::before,*::after{transition:none!important;animation:none!important}</style>'   # rows land at once, as under Reduce Motion
        cls.live = Path(cls.tmp.name) / 'live.html'
        cls.live.write_text(html.replace('<head>', '<head>' + still, 1))
        source, cls.binary = Path(cls.tmp.name) / 'page.swift', Path(cls.tmp.name) / 'page'
        source.write_text(HARNESS)
        built = subprocess.run(['swiftc', str(source), '-o', str(cls.binary)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_page(self, page, width, height, script):
        result = subprocess.run(
            [str(self.binary), str(page), str(width), str(height), script],
            capture_output=True, text=True, timeout=30, env={**os.environ, 'ARGO_DIR': self.tmp.name})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_every_page_and_provider_sheet_scroll_at_small_sizes(self):
        for width, height in ((640, 612), (480, 420), (360, 320)):
            with self.subTest(size=(width, height)):
                measured = json.loads(self.run_page(self.page, width, height, EVERY_PAGE)['result'])
                self.assertTrue(measured['sheet']['horizontal'])
                self.assertTrue(measured['sheet']['reachable'])
                for page in measured['rows']:
                    self.assertTrue(page['horizontal'], f"{page['id']} overflows horizontally at {width}×{height}")
                    self.assertGreater(page['actions'], 0, f"{page['id']} has no action")
                    self.assertTrue(page['reachable'], f"{page['id']} action is unreachable at {width}×{height}")

    def test_every_permission_row_scrolls_into_reach(self):
        for width, height in ((640, 612), (480, 420)):
            for granted in (False, True):
                with self.subTest(size=(width, height), granted=granted):
                    out = self.run_page(self.live, width, height, PERMISSION_ROWS.replace('GRANTED', str(granted).lower()))
                    rows = json.loads(out['result'])
                    self.assertIsInstance(rows, list, rows)
                    self.assertEqual([r['page'] for r in rows].count('perms'), 7)
                    self.assertEqual([r['page'] for r in rows].count('agents'), 7)
                    for r in rows:
                        where = f"{r['id']} at {width}×{height}"
                        self.assertTrue(r['inList'], f'{where} is clipped by its list')
                        self.assertTrue(r['onPage'], f'{where} cannot be scrolled into view')
                        self.assertTrue(r['name'] and r['why'], f'{where} name or description is hidden')
                        if granted:
                            self.assertTrue(r['check'], f'{where} does not show its check')
                        else:
                            self.assertTrue(r['allow'], f'{where} button cannot be clicked')
                    grants = [p['id'] for p in out['posts'] if p.get('do') == 'grant']
                    self.assertEqual(grants, [] if granted else [r['allow'] for r in rows])


if __name__ == '__main__':
    unittest.main()
