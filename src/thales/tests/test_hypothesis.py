from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from thales.models import HypothesisNote
from thales.tests.utils import authenticate, make_thales_user

URL = '/api/thales/hypothesis/'


class HypothesisNoteModelTest(TestCase):
    def test_has_no_foreign_key_fields(self):
        relations = [f for f in HypothesisNote._meta.get_fields() if f.is_relation]
        self.assertEqual(relations, [])

    def test_user_id_is_unique(self):
        HypothesisNote.objects.create(user_id=7, text='a')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HypothesisNote.objects.create(user_id=7, text='b')

    def test_text_defaults_to_empty_string(self):
        note = HypothesisNote.objects.create(user_id=8)
        self.assertEqual(note.text, '')


class HypothesisEndpointTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_thales_user('hypothesis-user')
        authenticate(self.client, self.user)

    def test_get_returns_empty_when_no_note(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json(),
            {'text': '', 'username': 'hypothesis-user', 'updated_at': None},
        )

    def test_put_creates_then_updates_own_note(self):
        r = self.client.put(URL, data={'text': 'first'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['text'], 'first')
        self.assertEqual(r.json()['username'], 'hypothesis-user')
        self.assertIsNotNone(r.json()['updated_at'])
        r = self.client.put(URL, data={'text': 'second'}, content_type='application/json')
        self.assertEqual(r.json()['text'], 'second')
        self.assertEqual(HypothesisNote.objects.filter(user_id=self.user.id).count(), 1)

    def test_put_accepts_unicode_and_newlines(self):
        text = 'DNA \u2014 \U0001F9EC\nline two'
        self.client.put(URL, data={'text': text}, content_type='application/json')
        self.assertEqual(self.client.get(URL).json()['text'], text)

    def test_put_rejects_text_over_limit(self):
        r = self.client.put(URL, data={'text': 'x' * 20001}, content_type='application/json')
        self.assertEqual(r.status_code, 422)
        self.assertEqual(HypothesisNote.objects.filter(user_id=self.user.id).count(), 0)

    def test_put_without_text_is_rejected_and_keeps_note(self):
        self.client.put(URL, data={'text': 'keep'}, content_type='application/json')
        r = self.client.put(URL, data={}, content_type='application/json')
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.get(URL).json()['text'], 'keep')

    def test_put_accepts_exactly_limit(self):
        r = self.client.put(URL, data={'text': 'x' * 20000}, content_type='application/json')
        self.assertEqual(r.status_code, 200)

    def test_anonymous_gets_401(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_user_without_thales_permission_gets_403(self):
        other = make_thales_user('no-thales-user', thales=False)
        client = Client()
        authenticate(client, other)
        self.assertEqual(client.get(URL).status_code, 403)
        r = client.put(URL, data={'text': 'nope'}, content_type='application/json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(HypothesisNote.objects.filter(user_id=other.id).count(), 0)


class HypothesisIsolationTest(TestCase):
    def test_users_cannot_see_each_others_note(self):
        client_a, client_b = Client(), Client()
        authenticate(client_a, make_thales_user('user-a'))
        authenticate(client_b, make_thales_user('user-b'))

        client_a.put(URL, data={'text': "A's note"}, content_type='application/json')
        self.assertEqual(client_b.get(URL).json()['text'], '')
        client_b.put(URL, data={'text': "B's note"}, content_type='application/json')
        self.assertEqual(client_a.get(URL).json()['text'], "A's note")
        self.assertEqual(client_b.get(URL).json()['text'], "B's note")
