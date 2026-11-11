"""Tests for the Thales literature advisor bridge.

Ported from thales2/llm_advisor/tests.py, with the URLs moved under
/api/thales/advisor/ and every request authenticated through the lab's
access control (the thales2 original mounted the advisor unauthenticated).
Lives at thales/tests/ like the rest of the lab's tests.

Ollama is always mocked: the tests must pass on machines without a model
runtime, and chat behaviour does not depend on the model's output beyond
the ANSWER_GUARD filter.
"""

import json
from unittest.mock import patch, Mock

import requests
from django.test import TestCase, Client

from thales.advisor.config import OLLAMA_PROBE_TIMEOUT, OLLAMA_TIMEOUT
from thales.tests.utils import authenticate, make_thales_user

CHAT_URL = '/api/thales/advisor/chat/'
RESET_URL = '/api/thales/advisor/reset/'
HEALTH_URL = '/api/thales/advisor/health/'


def _mock_ollama_response(mock_post, text='Here is what the data shows.'):
    mock_response = Mock()
    mock_response.raise_for_status = lambda: None
    mock_response.json = lambda: {'response': text}
    mock_post.return_value = mock_response


class AdvisorAccessControlTest(TestCase):
    """The advisor is part of the lab: it sits behind the Thales auth."""

    def setUp(self):
        self.client = Client()

    def test_anonymous_gets_401(self):
        response = self.client.get(HEALTH_URL)
        self.assertEqual(response.status_code, 401)

    def test_logged_in_user_without_thales_access_gets_403(self):
        user = make_thales_user('advisor-no-thales-access', thales=False)
        authenticate(self.client, user)
        response = self.client.get(HEALTH_URL)
        self.assertEqual(response.status_code, 403)


class AdvisorViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_thales_user('advisor-learner')
        authenticate(self.client, self.user)

    def _chat(self, payload):
        return self.client.post(
            CHAT_URL,
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_health(self):
        response = self.client.get(HEALTH_URL)
        self.assertEqual(response.status_code, 200)
        # Passive health: it never probes the model runtime, so the desk can
        # call it on every mount without waking a sleeping brain.
        self.assertEqual(response.json(), {'status': 'ok', 'brain': 'unknown'})

    @patch('thales.advisor.views.requests.get')
    def test_deep_health_reports_online_brain(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status = lambda: None
        mock_get.return_value = mock_response

        response = self.client.get(HEALTH_URL, {'deep': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'brain': 'online'})
        mock_get.assert_called_once_with(
            'http://localhost:11434/api/version',
            timeout=OLLAMA_PROBE_TIMEOUT,
        )

    @patch('thales.advisor.views.requests.get')
    def test_deep_health_reports_offline_brain(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError('no brain')

        response = self.client.get(HEALTH_URL, {'deep': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'brain': 'offline'})

    @patch('thales.advisor.views.requests.post')
    def test_chat_happy_path(self, mock_post):
        _mock_ollama_response(mock_post)
        response = self._chat({'question': 'What does Chargaff say about ratios?'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('session_id', data)
        self.assertEqual(data['questions_remaining'], 4)
        self.assertFalse(data['answer_guard_fired'])
        # The reply text from the mocked Ollama call passes through unchanged.
        self.assertEqual(data['reply'], 'Here is what the data shows.')

    @patch('thales.advisor.views.requests.post')
    def test_chat_queries_ollama_with_configured_model(self, mock_post):
        _mock_ollama_response(mock_post)
        self._chat({'question': 'What did Avery show?'})
        self.assertEqual(mock_post.call_count, 1)
        url = mock_post.call_args[0][0]
        payload = mock_post.call_args[1]['json']
        self.assertEqual(url, 'http://localhost:11434/api/generate')
        self.assertEqual(payload['model'], 'phi4-mini')
        self.assertEqual(payload['prompt'], 'What did Avery show?')
        self.assertEqual(payload['stream'], False)
        # Generation parameters belong under 'options'; Ollama ignores a
        # top-level 'temperature'.
        self.assertEqual(payload['options'], {'temperature': 0.7})
        self.assertNotIn('temperature', payload)
        # The request timeout comes from the advisor's own config, not a
        # hardcoded value (THALES_ADVISOR_OLLAMA_TIMEOUT setting ->
        # OLLAMA_TIMEOUT env -> 60s default).
        self.assertEqual(mock_post.call_args[1]['timeout'], OLLAMA_TIMEOUT)

    def test_chat_empty_question_returns_400(self):
        response = self._chat({'question': '   '})
        self.assertEqual(response.status_code, 400)

    @patch('thales.advisor.views.requests.post')
    def test_chat_limit_reached_returns_429(self, mock_post):
        _mock_ollama_response(mock_post)
        session_id = 'test-session-limit'
        for _ in range(5):
            self._chat({'question': 'a question', 'session_id': session_id})
        response = self._chat({'question': 'one more', 'session_id': session_id})
        self.assertEqual(response.status_code, 429)

    @patch('thales.advisor.views.requests.post')
    def test_chat_ollama_down_returns_503(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError('connection refused')
        session_id = 'test-session-ollama-down'
        response = self._chat({'question': 'anything at all', 'session_id': session_id})
        self.assertEqual(response.status_code, 503)
        # A failed query must not consume the learner's question: once the
        # runtime recovers, the session still has its full budget left.
        mock_post.side_effect = None
        _mock_ollama_response(mock_post)
        response = self._chat({'question': 'try again', 'session_id': session_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['questions_remaining'], 4)

    @patch('thales.advisor.views.requests.post')
    def test_answer_guard_filters_spoiler_replies(self, mock_post):
        _mock_ollama_response(mock_post, text='The DNA is a double helix, plainly.')
        response = self._chat({'question': 'What is the structure of DNA?'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['answer_guard_fired'])
        self.assertEqual(
            data['reply'],
            "That's not something anyone here can hand you outright — it's "
            "still unsolved, far as the published record goes. Tell me what "
            "evidence is pointing you that way, and I'll tell you whether it "
            "holds up against what we actually know.",
        )

    def test_reset_creates_fresh_session(self):
        response = self.client.post(
            RESET_URL, data=json.dumps({}), content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['questions_remaining'], 5)
        self.assertIn('session_id', data)
