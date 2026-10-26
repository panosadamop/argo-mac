"""Feedback privacy and instant routing; no browser or AI calls."""
import io
import json
import os
import subprocess
import sys
import unittest
import urllib.parse
from unittest.mock import patch
import argo
from tests import scratch_dir


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        for p in [patch.object(argo.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Mac14,5\n')),
                  patch.object(argo.platform, 'mac_ver', return_value=('26.0', (), ''))]:
            p.start(); self.addCleanup(p.stop)
        (self.root / 'log.jsonl').write_text(json.dumps({'task': 'Private ask /Users/person/name', 'reply': 'PRIVATE ANSWER', 'ran': ['PRIVATE COMMAND'], 'steps': ['Searching the web: PRIVATE QUERY']})+'\n'+json.dumps({'task': 'report feedback'})+'\n')

    def test_default_contains_only_template_and_whitelisted_environment(self):
        with patch.object(argo, 'github_repo', return_value=('panosadamop/argo-mac', 'main')):
            report = argo.feedback({'version': '9429210'})
        self.assertTrue(report['url'].startswith('https://github.com/panosadamop/argo-mac/issues/new?'))
        self.assertFalse(report['include'])
        self.assertIn('Mac model: Mac14,5', report['body'])
        self.assertIn('Version / commit: 9429210', report['body'])
        self.assertIn('Version: ' + argo.APP_VERSION, report['body']); self.assertIn('Routing: ', report['body'])
        self.assertNotIn('Install ID', report['body'])   # the issue is public: no identifiers
        for secret in ['Private ask', '/Users', 'PRIVATE ANSWER', 'PRIVATE COMMAND', str(self.root)]:
            self.assertNotIn(secret, report['body']); self.assertNotIn(urllib.parse.quote(secret), report['url'])
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(report['url']).query)
        self.assertEqual(query['body'], [report['body']])
        self.assertIn('What happened', report['body']); self.assertIn('What you expected', report['body'])

    def test_no_github_repo_gives_body_and_error_without_url(self):
        with patch.object(argo, 'github_repo', return_value=('', 'main')):
            report = argo.feedback({})
        self.assertNotIn('url', report); self.assertIn('github.repo', report['error']); self.assertIn('What happened', report['body'])

    def test_opt_in_shows_exact_previous_ask_only(self):
        report = argo.feedback({'include': True})
        self.assertIn('Private ask /Users/person/name', report['body'])
        self.assertNotIn('PRIVATE QUERY', report['body'])   # step names quote screen content and searches
        self.assertNotIn('PRIVATE ANSWER', report['body']); self.assertNotIn('PRIVATE COMMAND', report['body'])
        self.assertNotIn('report feedback', report['body'])
        self.assertTrue(report['include'])

    def test_feedback_always_waits_for_confirmation_and_skips_ai(self):
        for request in ('report feedback', 'report a bug'):
            with patch('sys.argv', ['argo.py', request]), patch.object(argo, 'start_claude') as ai, patch.object(argo, 'wait_commit', return_value=True) as gate, patch('sys.stdout', new_callable=io.StringIO) as out, patch.object(argo, 'look', return_value=[]), patch.object(argo, 'hands_map', return_value=None):
                argo.main()
                ai.assert_not_called(); gate.assert_called_once()
                self.assertIn('! feedback', out.getvalue())
                self.assertIn('Review your feedback', out.getvalue())
            with patch.dict(os.environ, {'ARGO_LIVE': '1'}, clear=True), patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertIsNone(argo.fast(request)); self.assertEqual(out.getvalue(), '')
