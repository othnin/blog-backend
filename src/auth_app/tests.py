"""
Unit tests for authentication endpoints and functionality.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core import mail
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import json

from auth_app.models import EmailVerificationToken, PasswordResetToken, UserProfile
from auth_app.utils import (
    generate_token,
    create_email_verification_token,
    create_password_reset_token,
)


class RegistrationTests(TestCase):
    """Tests for user registration endpoint."""
    
    def setUp(self):
        self.client = Client()
        self.register_url = '/api/auth/register'
    
    def test_register_success(self):
        """Test successful user registration."""
        data = {
            'email': 'testuser@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
            'username': 'testuser'
        }
        
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'success')
        
        # Check user was created
        user = User.objects.get(email='testuser@example.com')
        self.assertEqual(user.username, 'testuser')
        self.assertFalse(user.profile.email_verified)
    
    def test_register_auto_username(self):
        """Empty username string triggers auto-generation from the email local part."""
        data = {
            'email': 'newuser@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
            'username': '',  # blank → set_username validator generates from email
        }

        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.username, 'newuser')
    
    def test_register_duplicate_email(self):
        """Test registration fails with duplicate email."""
        # Create existing user
        User.objects.create_user(
            username='existing',
            email='existing@example.com',
            password='ValidPass123'
        )

        data = {
            'email': 'existing@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
            'username': 'someone',
        }

        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )

        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('already exists', response_data['message'])
    
    def test_register_password_mismatch(self):
        """Test registration fails when passwords don't match."""
        data = {
            'email': 'testuser@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'DifferentPass123',
        }
        
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Validation errors return 422 with Ninja's default error format
        self.assertNotEqual(response.status_code, 200)
        self.assertIn(b'error', response.content.lower())
    
    def test_register_weak_password(self):
        """Test registration fails with weak password."""
        weak_passwords = [
            'short',  # Too short
            'nouppercase123',  # No uppercase
            'NOLOWERCASE123',  # No lowercase
            'NoDigits',  # No digits
        ]
        
        for weak_pass in weak_passwords:
            data = {
                'email': f'user_{weak_passwords.index(weak_pass)}@example.com',
                'password': weak_pass,
                'password_confirm': weak_pass,
            }
            
            response = self.client.post(
                self.register_url,
                data=json.dumps(data),
                content_type='application/json'
            )
            
            # Validation errors return 422 with Ninja's default error format
            self.assertNotEqual(response.status_code, 200)
    
    def test_register_sends_verification_email(self):
        """Registration dispatches exactly one verification email to the registrant."""
        from django.test import override_settings
        data = {
            'email': 'testuser@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
            'username': 'testuser',
        }

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.client.post(
                self.register_url,
                data=json.dumps(data),
                content_type='application/json'
            )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['testuser@example.com'])


    def test_register_duplicate_username_auto_incremented(self):
        """When the requested username is taken, the serializer auto-increments it
        (e.g. 'taken' → 'taken1') and registration succeeds."""
        User.objects.create_user(
            username='taken',
            email='taken@example.com',
            password='ValidPass123'
        )

        data = {
            'email': 'other@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
            'username': 'taken',
        }

        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'success')
        # Username should have been deduplicated
        created_user = User.objects.get(email='other@example.com')
        self.assertNotEqual(created_user.username, 'taken')
        self.assertTrue(created_user.username.startswith('taken'))

    def test_register_response_shape(self):
        """Successful registration response includes status, message, and user object."""
        data = {
            'email': 'shaped@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
            'username': 'shaped',
        }

        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'success')
        self.assertIn('message', body)
        user = body['user']
        self.assertIn('id', user)
        self.assertEqual(user['username'], 'shaped')
        self.assertEqual(user['email'], 'shaped@example.com')
        self.assertFalse(user['email_verified'])

    def test_register_invalid_email_format(self):
        """A malformed email address is rejected before reaching the view."""
        data = {
            'email': 'not-an-email',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
            'username': 'anyuser',
        }

        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertNotEqual(response.status_code, 200)

    def test_register_creates_verification_token(self):
        """A valid registration creates exactly one EmailVerificationToken for the user."""
        data = {
            'email': 'tokencheck@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
            'username': 'tokencheck',
        }

        self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )

        user = User.objects.get(email='tokencheck@example.com')
        self.assertEqual(EmailVerificationToken.objects.filter(user=user).count(), 1)
        token = EmailVerificationToken.objects.get(user=user)
        self.assertTrue(token.is_valid())


# ---------------------------------------------------------------------------
# Auth Login Tests  (/api/auth/login)
# ---------------------------------------------------------------------------

class AuthLoginTests(TestCase):
    """Tests for POST /api/auth/login — session-style login returning user data."""

    def setUp(self):
        self.client = Client()
        self.login_url = '/api/auth/login'
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()

    def _post(self, data):
        return self.client.post(
            self.login_url,
            data=json.dumps(data),
            content_type='application/json'
        )

    def test_login_success(self):
        """Verified user with correct credentials receives a success response."""
        response = self._post({'username': 'testuser', 'password': 'ValidPass123'})
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'success')

    def test_login_response_shape(self):
        """Success response includes status, message, and a populated user object."""
        response = self._post({'username': 'testuser', 'password': 'ValidPass123'})
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'success')
        self.assertIn('message', body)
        user = body['user']
        self.assertIn('id', user)
        self.assertEqual(user['username'], 'testuser')
        self.assertEqual(user['email'], 'testuser@example.com')

    def test_login_wrong_password(self):
        """Wrong password returns status error."""
        response = self._post({'username': 'testuser', 'password': 'WrongPass999'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'error')

    def test_login_nonexistent_user(self):
        """Non-existent username returns status error."""
        response = self._post({'username': 'nobody', 'password': 'ValidPass123'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'error')

    def test_login_unverified_email(self):
        """User with unverified email is rejected with an error message."""
        self.user.profile.email_verified = False
        self.user.profile.save()

        response = self._post({'username': 'testuser', 'password': 'ValidPass123'})
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'error')
        self.assertIn('verified', body['message'].lower())

    def test_login_missing_password_field(self):
        """Request body without a password field is rejected at the serializer level."""
        response = self._post({'username': 'testuser'})
        self.assertNotEqual(response.status_code, 200)

    def test_login_missing_username_field(self):
        """Request body without a username field is rejected at the serializer level."""
        response = self._post({'password': 'ValidPass123'})
        self.assertNotEqual(response.status_code, 200)

    def test_login_does_not_return_jwt_tokens(self):
        """This endpoint validates identity but does not issue JWT tokens."""
        response = self._post({'username': 'testuser', 'password': 'ValidPass123'})
        body = json.loads(response.content)
        self.assertNotIn('access', body)
        self.assertNotIn('refresh', body)


class EmailVerificationTests(TestCase):
    """Tests for email verification endpoint."""
    
    def setUp(self):
        self.client = Client()
        self.verify_url = '/api/auth/verify-email'
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
    
    def test_verify_email_success(self):
        """Test successful email verification."""
        # Create verification token
        token = create_email_verification_token(self.user)
        
        data = {'token': token.token}
        
        response = self.client.post(
            self.verify_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'success')
        
        # Check user email marked as verified
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.email_verified)
        
        # Check token marked as used
        token.refresh_from_db()
        self.assertTrue(token.is_used)
    
    def test_verify_email_invalid_token(self):
        """Test verification fails with invalid token."""
        data = {'token': 'invalid-token'}
        
        response = self.client.post(
            self.verify_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('not found', response_data['message'])
    
    def test_verify_email_expired_token(self):
        """Test verification fails with expired token."""
        # Create expired token
        token = EmailVerificationToken.objects.create(
            user=self.user,
            token=generate_token(),
            expires_at=timezone.now() - timedelta(hours=1),
        )
        
        data = {'token': token.token}
        
        response = self.client.post(
            self.verify_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('expired', response_data['message'])
    
    def test_verify_email_already_used_token(self):
        """Test verification fails with already used token."""
        token = create_email_verification_token(self.user)
        token.is_used = True
        token.save()

        data = {'token': token.token}

        response = self.client.post(
            self.verify_url,
            data=json.dumps(data),
            content_type='application/json'
        )

        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')

    def test_verify_email_response_includes_user_data(self):
        """Successful verification returns a user object in the response."""
        token = create_email_verification_token(self.user)

        response = self.client.post(
            self.verify_url,
            data=json.dumps({'token': token.token}),
            content_type='application/json'
        )

        body = json.loads(response.content)
        self.assertEqual(body['status'], 'success')
        user = body['user']
        self.assertEqual(user['username'], 'testuser')
        self.assertEqual(user['email'], 'testuser@example.com')
        self.assertTrue(user['email_verified'])

    def test_verify_email_already_verified_user(self):
        """A user whose email is already verified can still consume a fresh valid token."""
        self.user.profile.email_verified = True
        self.user.profile.save()
        token = create_email_verification_token(self.user)

        response = self.client.post(
            self.verify_url,
            data=json.dumps({'token': token.token}),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'success')

    def test_verify_email_empty_token(self):
        """An empty token string is rejected."""
        response = self.client.post(
            self.verify_url,
            data=json.dumps({'token': ''}),
            content_type='application/json'
        )

        body = json.loads(response.content)
        self.assertEqual(body['status'], 'error')


class PasswordResetTests(TestCase):
    """Tests for password reset endpoints."""
    
    def setUp(self):
        self.client = Client()
        self.reset_request_url = '/api/auth/password-reset-request'
        self.reset_confirm_url = '/api/auth/password-reset-confirm'
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='OldPass123'
        )
    
    def test_password_reset_request_success(self):
        """Test successful password reset request."""
        data = {'email': 'testuser@example.com'}
        
        response = self.client.post(
            self.reset_request_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'success')
        
        # Check reset token was created
        self.assertTrue(PasswordResetToken.objects.filter(user=self.user).exists())
    
    def test_password_reset_request_nonexistent_email(self):
        """Test password reset request with non-existent email (should not reveal)."""
        data = {'email': 'nonexistent@example.com'}
        
        response = self.client.post(
            self.reset_request_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        response_data = json.loads(response.content)
        # Should return success to prevent email enumeration
        self.assertEqual(response_data['status'], 'success')
    
    def test_password_reset_confirm_success(self):
        """Test successful password reset confirmation."""
        # Create reset token
        token = create_password_reset_token(self.user)
        
        data = {
            'token': token.token,
            'new_password': 'NewPass123',
            'new_password_confirm': 'NewPass123',
        }
        
        response = self.client.post(
            self.reset_confirm_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'success')
        
        # Check token marked as used
        token.refresh_from_db()
        self.assertTrue(token.is_used)
        
        # Check password was changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass123'))
        self.assertFalse(self.user.check_password('OldPass123'))
    
    def test_password_reset_confirm_invalid_token(self):
        """Test password reset fails with invalid token."""
        data = {
            'token': 'invalid-token',
            'new_password': 'NewPass123',
            'new_password_confirm': 'NewPass123',
        }
        
        response = self.client.post(
            self.reset_confirm_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
    
    def test_password_reset_confirm_expired_token(self):
        """Test password reset fails with expired token."""
        token = PasswordResetToken.objects.create(
            user=self.user,
            token=generate_token(),
            expires_at=timezone.now() - timedelta(hours=1),
        )
        
        data = {
            'token': token.token,
            'new_password': 'NewPass123',
            'new_password_confirm': 'NewPass123',
        }
        
        response = self.client.post(
            self.reset_confirm_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Should return 200 with error status
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('expired', response_data['message'].lower())
    
    def test_password_reset_confirm_password_mismatch(self):
        """Test password reset fails when new passwords don't match."""
        token = create_password_reset_token(self.user)
        
        data = {
            'token': token.token,
            'new_password': 'NewPass123',
            'new_password_confirm': 'DifferentPass123',
        }
        
        response = self.client.post(
            self.reset_confirm_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Validation errors return 422 with Ninja's default error format
        self.assertNotEqual(response.status_code, 200)
    
    def test_password_reset_confirm_weak_password(self):
        """Test password reset fails with weak new password."""
        token = create_password_reset_token(self.user)

        weak_passwords = [
            ('short', 'short'),
            ('nouppercase123', 'nouppercase123'),
            ('NOLOWERCASE123', 'NOLOWERCASE123'),
            ('NoDigits', 'NoDigits'),
        ]

        for weak_pass, confirm in weak_passwords:
            data = {
                'token': token.token,
                'new_password': weak_pass,
                'new_password_confirm': confirm,
            }

            response = self.client.post(
                self.reset_confirm_url,
                data=json.dumps(data),
                content_type='application/json'
            )

            # Validation errors return 422 with Ninja's default error format
            self.assertNotEqual(response.status_code, 200)

    def test_password_reset_confirm_used_token_rejected(self):
        """A token that has already been used to reset a password cannot be reused."""
        token = create_password_reset_token(self.user)
        token.is_used = True
        token.save()

        data = {
            'token': token.token,
            'new_password': 'NewPass123',
            'new_password_confirm': 'NewPass123',
        }

        response = self.client.post(
            self.reset_confirm_url,
            data=json.dumps(data),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'error')

    def test_password_reset_confirm_allows_login_with_new_password(self):
        """After a successful reset the user can log in with the new password."""
        token = create_password_reset_token(self.user)

        self.client.post(
            self.reset_confirm_url,
            data=json.dumps({
                'token': token.token,
                'new_password': 'BrandNew456',
                'new_password_confirm': 'BrandNew456',
            }),
            content_type='application/json'
        )

        login_response = self.client.post(
            '/api/token/pair',
            data=json.dumps({'username': 'testuser', 'password': 'BrandNew456'}),
            content_type='application/json'
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertIn('access', json.loads(login_response.content))

    def test_password_reset_confirm_old_password_no_longer_works(self):
        """After reset, the original password is rejected."""
        token = create_password_reset_token(self.user)

        self.client.post(
            self.reset_confirm_url,
            data=json.dumps({
                'token': token.token,
                'new_password': 'BrandNew456',
                'new_password_confirm': 'BrandNew456',
            }),
            content_type='application/json'
        )

        login_response = self.client.post(
            '/api/token/pair',
            data=json.dumps({'username': 'testuser', 'password': 'OldPass123'}),
            content_type='application/json'
        )
        self.assertEqual(login_response.status_code, 401)

    def test_password_reset_request_invalid_email_format(self):
        """A malformed email in the reset request is rejected by the serializer."""
        response = self.client.post(
            self.reset_request_url,
            data=json.dumps({'email': 'not-an-email'}),
            content_type='application/json'
        )
        self.assertNotEqual(response.status_code, 200)

    def test_password_reset_request_same_message_for_existing_and_nonexisting(self):
        """The response message is identical whether or not the email exists (no enumeration)."""
        real_response = self.client.post(
            self.reset_request_url,
            data=json.dumps({'email': 'testuser@example.com'}),
            content_type='application/json'
        )
        fake_response = self.client.post(
            self.reset_request_url,
            data=json.dumps({'email': 'ghost@example.com'}),
            content_type='application/json'
        )

        real_msg = json.loads(real_response.content)['message']
        fake_msg = json.loads(fake_response.content)['message']
        self.assertEqual(real_msg, fake_msg)

    def test_password_reset_request_sends_email(self):
        """A reset request for a real account dispatches exactly one email."""
        from django.test import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.client.post(
                self.reset_request_url,
                data=json.dumps({'email': 'testuser@example.com'}),
                content_type='application/json'
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['testuser@example.com'])

    def test_password_reset_request_no_email_sent_for_nonexistent_user(self):
        """A reset request for an unknown email sends no email."""
        from django.test import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.client.post(
                self.reset_request_url,
                data=json.dumps({'email': 'ghost@example.com'}),
                content_type='application/json'
            )
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# Auth Me Tests  (GET /api/auth/me)
# ---------------------------------------------------------------------------

class AuthMeTests(TestCase):
    """Tests for GET /api/auth/me — returns authenticated user's profile."""

    def setUp(self):
        self.client = Client()
        self.me_url = '/api/auth/me'
        self.token_url = '/api/token/pair'
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()

    def _get_access_token(self, username='testuser', password='ValidPass123'):
        response = self.client.post(
            self.token_url,
            data=json.dumps({'username': username, 'password': password}),
            content_type='application/json'
        )
        return json.loads(response.content)['access']

    def test_authenticated_returns_200(self):
        """A valid JWT token grants access to /api/auth/me."""
        token = self._get_access_token()
        response = self.client.get(self.me_url, HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_returns_401(self):
        """No token → 401 (JWTAuth rejects, not IsAuthenticated permission)."""
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_returns_401(self):
        """A malformed Bearer token is rejected with 401."""
        response = self.client.get(self.me_url, HTTP_AUTHORIZATION='Bearer garbage.token')
        self.assertEqual(response.status_code, 401)

    def test_response_shape(self):
        """Response includes id, username, email, email_verified, and profile."""
        token = self._get_access_token()
        response = self.client.get(self.me_url, HTTP_AUTHORIZATION=f'Bearer {token}')
        body = json.loads(response.content)
        self.assertIn('id', body)
        self.assertIn('username', body)
        self.assertIn('email', body)
        self.assertIn('profile', body)
        self.assertEqual(body['username'], 'testuser')
        self.assertEqual(body['email'], 'testuser@example.com')

    def test_response_includes_role_in_profile(self):
        """Profile object in response contains the user's role."""
        token = self._get_access_token()
        response = self.client.get(self.me_url, HTTP_AUTHORIZATION=f'Bearer {token}')
        body = json.loads(response.content)
        self.assertIn('role', body['profile'])
        self.assertEqual(body['profile']['role'], 'reader')  # default role

    def test_editor_role_reflected_in_response(self):
        """An editor's profile shows the editor role."""
        self.user.profile.role = 'editor'
        self.user.profile.save()
        token = self._get_access_token()
        response = self.client.get(self.me_url, HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(json.loads(response.content)['profile']['role'], 'editor')

    def test_admin_role_reflected_in_response(self):
        """An admin's profile shows the admin role."""
        self.user.profile.role = 'admin'
        self.user.profile.save()
        token = self._get_access_token()
        response = self.client.get(self.me_url, HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(json.loads(response.content)['profile']['role'], 'admin')

    def test_returns_data_for_requesting_user_only(self):
        """Each user sees their own data, not another user's."""
        other = User.objects.create_user(
            username='other', email='other@example.com', password='ValidPass123'
        )
        other.profile.email_verified = True
        other.profile.save()

        token = self._get_access_token(username='other')
        response = self.client.get(self.me_url, HTTP_AUTHORIZATION=f'Bearer {token}')
        body = json.loads(response.content)
        self.assertEqual(body['username'], 'other')
        self.assertEqual(body['email'], 'other@example.com')


class TokenModelTests(TestCase):
    """Tests for token models."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
    
    def test_email_verification_token_is_valid(self):
        """Test EmailVerificationToken.is_valid() method."""
        # Valid token
        token = EmailVerificationToken.objects.create(
            user=self.user,
            token=generate_token(),
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.assertTrue(token.is_valid())
        
        # Expired token
        expired_token = EmailVerificationToken.objects.create(
            user=self.user,
            token=generate_token(),
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(expired_token.is_valid())
        
        # Used token
        used_token = EmailVerificationToken.objects.create(
            user=self.user,
            token=generate_token(),
            expires_at=timezone.now() + timedelta(hours=1),
            is_used=True,
        )
        self.assertFalse(used_token.is_valid())
    
    def test_password_reset_token_is_valid(self):
        """Test PasswordResetToken.is_valid() method."""
        # Valid token
        token = PasswordResetToken.objects.create(
            user=self.user,
            token=generate_token(),
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.assertTrue(token.is_valid())
        
        # Expired token
        expired_token = PasswordResetToken.objects.create(
            user=self.user,
            token=generate_token(),
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(expired_token.is_valid())
        
        # Used token
        used_token = PasswordResetToken.objects.create(
            user=self.user,
            token=generate_token(),
            expires_at=timezone.now() + timedelta(hours=1),
            is_used=True,
        )
        self.assertFalse(used_token.is_valid())
    
    def test_user_profile_created_on_user_creation(self):
        """Test UserProfile is automatically created when User is created."""
        new_user = User.objects.create_user(
            username='newuser',
            email='newuser@example.com',
            password='ValidPass123'
        )

        self.assertTrue(hasattr(new_user, 'profile'))
        self.assertFalse(new_user.profile.email_verified)


class JWTTokenTests(TestCase):
    """Tests for JWT login endpoint and token-protected routes."""

    def setUp(self):
        self.client = Client()
        self.token_url = '/api/token/pair'
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()

    def test_login_with_username_returns_tokens(self):
        """Successful login returns access and refresh tokens."""
        data = {'username': 'testuser', 'password': 'ValidPass123'}
        response = self.client.post(
            self.token_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertIn('access', response_data)
        self.assertIn('refresh', response_data)

    def test_login_with_email_returns_tokens(self):
        """Login accepts email as the username field."""
        data = {'username': 'testuser@example.com', 'password': 'ValidPass123'}
        response = self.client.post(
            self.token_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertIn('access', response_data)

    def test_login_invalid_password_returns_401(self):
        """Wrong password is rejected."""
        data = {'username': 'testuser', 'password': 'WrongPass999'}
        response = self.client.post(
            self.token_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_login_nonexistent_user_returns_401(self):
        """Non-existent username is rejected."""
        data = {'username': 'nobody', 'password': 'ValidPass123'}
        response = self.client.post(
            self.token_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_login_unverified_email_blocked_when_verification_required(self):
        """User with unverified email cannot log in when SKIP_EMAIL_VERIFICATION is False."""
        from django.test import override_settings
        self.user.profile.email_verified = False
        self.user.profile.save()
        data = {'username': 'testuser', 'password': 'ValidPass123'}
        with override_settings(SKIP_EMAIL_VERIFICATION=False):
            response = self.client.post(
                self.token_url,
                data=json.dumps(data),
                content_type='application/json'
            )
        self.assertEqual(response.status_code, 401)

    def test_protected_endpoint_without_token_returns_403(self):
        """Unauthenticated requests to protected endpoints return 403 (IsAuthenticated permission)."""
        response = self.client.get('/api/blog/my-posts/')
        self.assertEqual(response.status_code, 403)

    def test_protected_endpoint_with_invalid_token_returns_403(self):
        """Requests with a malformed Bearer token to protected endpoints return 403."""
        response = self.client.get(
            '/api/blog/my-posts/',
            HTTP_AUTHORIZATION='Bearer not.a.real.token'
        )
        self.assertEqual(response.status_code, 403)

    def test_login_response_includes_username(self):
        """Successful login response includes the username field."""
        data = {'username': 'testuser', 'password': 'ValidPass123'}
        response = self.client.post(
            self.token_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        body = json.loads(response.content)
        self.assertIn('username', body)
        self.assertEqual(body['username'], 'testuser')

    def test_login_skip_email_verification_allows_unverified(self):
        """When SKIP_EMAIL_VERIFICATION=True, unverified users can still log in."""
        from django.test import override_settings
        self.user.profile.email_verified = False
        self.user.profile.save()
        data = {'username': 'testuser', 'password': 'ValidPass123'}
        with override_settings(SKIP_EMAIL_VERIFICATION=True):
            response = self.client.post(
                self.token_url,
                data=json.dumps(data),
                content_type='application/json'
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', json.loads(response.content))

    def test_login_missing_password_returns_error(self):
        """Omitting the password field is rejected at the serializer level."""
        response = self.client.post(
            self.token_url,
            data=json.dumps({'username': 'testuser'}),
            content_type='application/json'
        )
        self.assertNotEqual(response.status_code, 200)

    def test_login_empty_body_returns_error(self):
        """An empty JSON body is rejected."""
        response = self.client.post(
            self.token_url,
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertNotEqual(response.status_code, 200)


class JWTRefreshTests(TestCase):
    """Tests for POST /api/token/refresh — token refresh and rotation."""

    def setUp(self):
        self.client = Client()
        self.token_url = '/api/token/pair'
        self.refresh_url = '/api/token/refresh'
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()

    def _get_tokens(self):
        """Helper: log in and return (access, refresh) token strings."""
        response = self.client.post(
            self.token_url,
            data=json.dumps({'username': 'testuser', 'password': 'ValidPass123'}),
            content_type='application/json'
        )
        data = json.loads(response.content)
        return data['access'], data['refresh']

    def test_valid_refresh_token_returns_new_access_token(self):
        """A valid refresh token yields a fresh access token."""
        _, refresh = self._get_tokens()
        response = self.client.post(
            self.refresh_url,
            data=json.dumps({'refresh': refresh}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('access', data)

    def test_rotation_returns_new_refresh_token(self):
        """With ROTATE_REFRESH_TOKENS=True, refresh also returns a new refresh token."""
        from django.test import override_settings
        import datetime
        with override_settings(NINJA_JWT={
            'ACCESS_TOKEN_LIFETIME': datetime.timedelta(minutes=60),
            'REFRESH_TOKEN_LIFETIME': datetime.timedelta(days=7),
            'ROTATE_REFRESH_TOKENS': True,
            'BLACKLIST_AFTER_ROTATION': True,
        }):
            _, refresh = self._get_tokens()
            response = self.client.post(
                self.refresh_url,
                data=json.dumps({'refresh': refresh}),
                content_type='application/json'
            )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('refresh', data)
        self.assertNotEqual(data['refresh'], refresh)

    def test_rotated_old_refresh_token_is_rejected(self):
        """After rotation, the original refresh token cannot be reused."""
        from django.test import override_settings
        import datetime
        with override_settings(NINJA_JWT={
            'ACCESS_TOKEN_LIFETIME': datetime.timedelta(minutes=60),
            'REFRESH_TOKEN_LIFETIME': datetime.timedelta(days=7),
            'ROTATE_REFRESH_TOKENS': True,
            'BLACKLIST_AFTER_ROTATION': True,
        }):
            _, refresh = self._get_tokens()
            # First use — rotates the token
            self.client.post(
                self.refresh_url,
                data=json.dumps({'refresh': refresh}),
                content_type='application/json'
            )
            # Second use of the original token — must be rejected
            response = self.client.post(
                self.refresh_url,
                data=json.dumps({'refresh': refresh}),
                content_type='application/json'
            )
        self.assertEqual(response.status_code, 401)

    def test_invalid_refresh_token_returns_401(self):
        """A garbage string is rejected with 401."""
        response = self.client.post(
            self.refresh_url,
            data=json.dumps({'refresh': 'not.a.real.token'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_missing_refresh_field_returns_error(self):
        """Request body without a 'refresh' field is rejected."""
        response = self.client.post(
            self.refresh_url,
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertNotEqual(response.status_code, 200)

    def test_refreshed_access_token_grants_protected_access(self):
        """Access token obtained via refresh can authenticate protected endpoints."""
        _, refresh = self._get_tokens()
        refresh_response = self.client.post(
            self.refresh_url,
            data=json.dumps({'refresh': refresh}),
            content_type='application/json'
        )
        new_access = json.loads(refresh_response.content)['access']
        protected_response = self.client.get(
            '/api/me',
            HTTP_AUTHORIZATION=f'Bearer {new_access}'
        )
        self.assertEqual(protected_response.status_code, 200)


class JWTBlacklistTests(TestCase):
    """Tests for POST /api/token/blacklist — logout token revocation."""

    def setUp(self):
        self.client = Client()
        self.token_url = '/api/token/pair'
        self.refresh_url = '/api/token/refresh'
        self.blacklist_url = '/api/token/blacklist'
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()

    def _get_tokens(self):
        response = self.client.post(
            self.token_url,
            data=json.dumps({'username': 'testuser', 'password': 'ValidPass123'}),
            content_type='application/json'
        )
        data = json.loads(response.content)
        return data['access'], data['refresh']

    def test_blacklist_valid_refresh_token_returns_200(self):
        """Blacklisting a valid refresh token succeeds."""
        _, refresh = self._get_tokens()
        response = self.client.post(
            self.blacklist_url,
            data=json.dumps({'refresh': refresh}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

    def test_blacklisted_token_cannot_be_used_to_refresh(self):
        """A token that has been blacklisted is rejected by the refresh endpoint."""
        _, refresh = self._get_tokens()
        # Blacklist the token
        self.client.post(
            self.blacklist_url,
            data=json.dumps({'refresh': refresh}),
            content_type='application/json'
        )
        # Attempt to refresh with the now-blacklisted token
        response = self.client.post(
            self.refresh_url,
            data=json.dumps({'refresh': refresh}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_blacklist_invalid_token_returns_400(self):
        """Attempting to blacklist a garbage token returns 400."""
        response = self.client.post(
            self.blacklist_url,
            data=json.dumps({'refresh': 'garbage.token.value'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_blacklist_already_blacklisted_token_returns_400(self):
        """Double-blacklisting the same token returns 400 on the second attempt."""
        _, refresh = self._get_tokens()
        self.client.post(
            self.blacklist_url,
            data=json.dumps({'refresh': refresh}),
            content_type='application/json'
        )
        response = self.client.post(
            self.blacklist_url,
            data=json.dumps({'refresh': refresh}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
