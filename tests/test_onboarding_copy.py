"""Setup (ui/onboarding.html) shows the app as it is today. Source checks only: no window, app or WebKit."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OnboardingMatchesAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / 'ui/onboarding.html').read_text()

    def test_dictation_pill_shows_no_words(self):
        pill = self.page.split('id="dc-pill">', 1)[1].split('</div>', 1)[0]
        self.assertNotIn('dc-said', pill)   # the pill has no transcript any more
        for part in ('class="wv"', 'class="orb"', '<svg'):
            self.assertIn(part, pill)   # wave, then the orb, then the check
        loop = self.page.split('async dictate()', 1)[1].split('async work()', 1)[0]
        self.assertLess(loop.index("pill.classList.add('work')"), loop.index("pill.classList.replace('work', 'done')"))

    @unittest.skipUnless(shutil.which('node'), 'node runs the keycap split')
    def test_talk_keys_follow_the_configured_shortcut(self):
        caps = re.search(r'  const capsOf = .*\n', self.page).group(0)
        script = caps + '''
const want = {'⌃⌥Space': ['⌃', '⌥', 'Space'], 'fn': ['fn'], 'fn⌃': ['fn', '⌃'], '⌘⇧A': ['⌘', '⇧', 'A'], 'F5': ['F5']};
for (const [label, keys] of Object.entries(want)) if (JSON.stringify(capsOf(label)) !== JSON.stringify(keys)) { console.error(label, capsOf(label)); process.exit(1); }'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        swift = (ROOT / 'Argo.swift').read_text()
        self.assertIn('"hotkeyLabel": Prefs.str("hotkeyLabel")', swift)   # setup draws the keys the user set
        self.assertIn('call("ob.keys", shortcutModifierLabel(NSEvent.modifierFlags))', swift)   # any held modifier lights, not only ⌃⌥
        self.assertNotIn('id="t1"', self.page)

    def test_work_demo_box_does_not_mirror_agent_steps(self):
        self.assertNotIn('Moving to an agent', self.page)   # the box says it started once; steps live on the chip
        loop = self.page.split('async work()', 1)[1].split('async point()', 1)[0]
        self.assertIn('line.textContent = WK_STARTED', loop)
        self.assertIn("'Agent · done'", loop)

    def test_point_demo_runs_the_leader_line_before_the_ring(self):
        loop = self.page.split('async point()', 1)[1].split('async done()', 1)[0]
        self.assertLess(loop.index('lead();'), loop.index("ring.classList.add('on')"))   # the ring shows as the line arrives, as on screen
        self.assertIn('id="pt-lead"', self.page)
        self.assertIn('stop-color="#0a84ff"', self.page)   # blue, like the app's leader

    def test_safe_mode_line_shows_only_while_it_is_on(self):
        self.assertIn("$('safe-note').hidden = prefs.safe === false", self.page)
        self.assertIn('"safe": Prefs.bool("safe")', (ROOT / 'Argo.swift').read_text())

    def test_mini_screen_copy_matches_its_click(self):
        self.assertNotIn('ask to focus it', self.page)
        self.assertIn('click it to open that window', self.page)   # the mini screen opens its window on click (README)

    def test_meeting_page_says_what_devin_and_pi_get(self):
        brain = (ROOT / 'argo.py').read_text()
        self.assertIn("if client() != 'claude':\n        raise RuntimeError(f'Meeting Copilot stays on this Mac", brain)   # no answers off Claude
        self.assertIn("$('mt-hint').textContent = other ? `With ${NAMES[provider]}, it saves the transcript on this Mac. Answers and recaps need Claude.`", self.page)

    def test_provider_row_names_no_client_before_the_check(self):
        self.assertIn("['claude', 'AI Provider', 'Checking…',", self.page)   # Devin, Pi and server users never read "Claude" first
        self.assertNotIn('Checking your Claude sign-in', self.page)
        self.assertIn("$('wk-brain').hidden = $('wk-plan').hidden = provider === 'server'", self.page)   # no plan to choose on a custom server

    def test_failed_asks_only_open_setup_automatically_once_per_launch(self):
        swift = (ROOT / 'Argo.swift').read_text()
        opening = swift.split('    func open(automatic: Bool = false) {', 1)[1].split('        screenInitiallyGranted', 1)[0]
        self.assertIn('if automatic && setupShown { return }', opening)
        self.assertLess(opening.index('if automatic && setupShown'), opening.index('setupShown = true'))
        self.assertLess(opening.index('setupShown = true'), opening.index('guard win == nil'))
        self.assertIn('setupShown = false', swift)
        self.assertEqual(swift.count('setupShown = true'), 1)
        self.assertIn('if line == "! setup" { onboarding.open(automatic: true); continue }', swift)
        self.assertIn('case "setup": onboarding.open()', swift)   # explicit setup stays available after dismissal
        self.assertIn('if !UserDefaults.standard.bool(forKey: "onboarded") { DispatchQueue.main.async { onboarding.open() } }', swift)
        self.assertIn('else { Onboarding.plan { c in if c["ok"] as? Bool != true { onboarding.open(automatic: true) } } }', swift)
        self.assertIn("if automatic {", swift.split('    func open(automatic: Bool = false) {', 1)[1].split('loadPage(v', 1)[0])   # automatic opens skip the welcome
        self.assertIn("window.obStart = 'perms'", swift)
        self.assertIn("go(window.obStart || 'welcome')", (ROOT / 'ui' / 'onboarding.html').read_text())

    def test_setup_opens_settings_for_invalid_configuration_before_signin(self):
        swift = (ROOT / 'Argo.swift').read_text()
        fix = swift.split('    func fixPlan() {', 1)[1].split('    func tried()', 1)[0]
        self.assertIn('if need.isEmpty, c["ok"] as? Bool == false { Argo.settings.open(); return }', fix)
        self.assertLess(fix.index('if need.isEmpty'), fix.index('let cmd ='))

    def test_setup_checks_one_provider_process_at_a_time(self):
        swift = (ROOT / 'Argo.swift').read_text()
        check = swift.split('    func checkPlan() {', 1)[1].split('\n    }', 1)[0]
        self.assertIn('guard !checkingPlan else { return }', check)
        self.assertLess(check.index('checkingPlan = true'), check.index('Onboarding.plan'))
        self.assertIn('self?.checkingPlan = false', check)

    def test_voice_asks_use_the_mac_language(self):
        swift = (ROOT / 'Argo.swift').read_text()
        speech = swift.split('    func speechModule(dictate: Bool = false)', 1)[1].split('    func prepareSpeech()', 1)[0]
        self.assertNotIn('Locale.current', speech)   # SpeechTranscriber rejected the Mac's locale: every voice ask died in 1.5.0
        self.assertIn(': SpeechTranscriber(locale: locale, preset: .progressiveTranscription)', speech)
        start = swift.split('    func start(dictate: Bool)', 1)[1].split('    func heard(', 1)[0]
        self.assertIn('dictate || SFSpeechRecognizer.authorizationStatus() == .authorized', start)
        self.assertIn('Privacy & Security → Speech Recognition.', start)
        prepare = swift.split('    func prepareSpeech()', 1)[1].split('    var text =', 1)[0]
        self.assertIn('guard !preparingSpeech else { return }', prepare)


if __name__ == '__main__':
    unittest.main()
