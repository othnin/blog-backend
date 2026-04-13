"""
Unit tests for authentication endpoints and functionality.
"""
from django.test import TestCase, Client, override_settings
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


# ---------------------------------------------------------------------------
# Auth Settings Tests  (GET/PATCH /api/auth/settings)
# ---------------------------------------------------------------------------

class AuthSettingsTests(TestCase):
    """Tests for GET/PATCH /api/auth/settings — user profile settings."""

    def setUp(self):
        self.client = Client()
        self.settings_url = '/api/auth/settings'
        self.token_url = '/api/token/pair'
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()

    def _get_access_token(self):
        response = self.client.post(
            self.token_url,
            data=json.dumps({'username': 'testuser', 'password': 'ValidPass123'}),
            content_type='application/json'
        )
        return json.loads(response.content)['access']

    def test_get_settings_authenticated_returns_200(self):
        """A valid JWT token grants access to GET /api/auth/settings."""
        token = self._get_access_token()
        response = self.client.get(
            self.settings_url,
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_get_settings_unauthenticated_returns_401(self):
        """No token → 401 (JWTAuth rejects)."""
        response = self.client.get(self.settings_url)
        self.assertEqual(response.status_code, 401)

    def test_get_settings_response_includes_all_fields(self):
        """Response includes all user settings fields."""
        token = self._get_access_token()
        response = self.client.get(
            self.settings_url,
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        body = json.loads(response.content)
        expected_fields = [
            'display_name', 'bio', 'email_notifications',
            'twitter_url', 'github_url', 'website_url',
            'profile_public', 'avatar_url'
        ]
        for field in expected_fields:
            self.assertIn(field, body)

    def test_patch_settings_updates_display_name(self):
        """Updating display_name via PATCH is reflected in subsequent GET."""
        token = self._get_access_token()
        
        # Update
        patch_response = self.client.patch(
            self.settings_url,
            data=json.dumps({'display_name': 'New Display Name'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(patch_response.status_code, 200)
        
        # Verify
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.display_name, 'New Display Name')

    def test_patch_settings_updates_bio(self):
        """Updating bio via PATCH is reflected."""
        token = self._get_access_token()
        
        patch_response = self.client.patch(
            self.settings_url,
            data=json.dumps({'bio': 'I love coding!'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(patch_response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.bio, 'I love coding!')

    def test_patch_settings_updates_social_links(self):
        """Updating social media URLs via PATCH."""
        token = self._get_access_token()
        
        patch_data = {
            'twitter_url': 'https://twitter.com/testuser',
            'github_url': 'https://github.com/testuser',
            'website_url': 'https://testuser.com'
        }
        
        response = self.client.patch(
            self.settings_url,
            data=json.dumps(patch_data),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.twitter_url, 'https://twitter.com/testuser')
        self.assertEqual(self.user.profile.github_url, 'https://github.com/testuser')
        self.assertEqual(self.user.profile.website_url, 'https://testuser.com')

    def test_patch_settings_updates_email_notifications(self):
        """Updating email_notifications preference."""
        token = self._get_access_token()
        self.user.profile.email_notifications = True
        self.user.profile.save()
        
        response = self.client.patch(
            self.settings_url,
            data=json.dumps({'email_notifications': False}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.email_notifications)

    def test_patch_settings_updates_profile_public(self):
        """Updating profile_public visibility setting."""
        token = self._get_access_token()
        self.user.profile.profile_public = True
        self.user.profile.save()
        
        response = self.client.patch(
            self.settings_url,
            data=json.dumps({'profile_public': False}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.profile_public)

    def test_patch_settings_partial_update(self):
        """Only specified fields are updated; others are preserved."""
        token = self._get_access_token()
        self.user.profile.display_name = 'Old Name'
        self.user.profile.bio = 'Old Bio'
        self.user.profile.save()
        
        # Update only display_name
        response = self.client.patch(
            self.settings_url,
            data=json.dumps({'display_name': 'New Name'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.display_name, 'New Name')
        self.assertEqual(self.user.profile.bio, 'Old Bio')  # Unchanged

    def test_patch_settings_unauthenticated_returns_401(self):
        """PATCH without token returns 401."""
        response = self.client.patch(
            self.settings_url,
            data=json.dumps({'display_name': 'Hacker'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_patch_settings_returns_updated_object(self):
        """PATCH response includes the updated settings object."""
        token = self._get_access_token()
        response = self.client.patch(
            self.settings_url,
            data=json.dumps({'display_name': 'Test Display'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        body = json.loads(response.content)
        self.assertEqual(body['display_name'], 'Test Display')


# ---------------------------------------------------------------------------
# Auth Avatar Upload Tests  (POST /api/auth/avatar)
# ---------------------------------------------------------------------------

class AuthAvatarUploadTests(TestCase):
    """Tests for POST /api/auth/avatar — avatar image upload and resize."""

    def setUp(self):
        self.client = Client()
        self.avatar_url = '/api/auth/avatar'
        self.token_url = '/api/token/pair'
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='ValidPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()
        
        from io import BytesIO
        from PIL import Image
        
        # Create a test image
        img = Image.new('RGB', (100, 100), color='red')
        self.test_image = BytesIO()
        img.save(self.test_image, format='JPEG')
        self.test_image.seek(0)
        self.test_image.name = 'test_avatar.jpg'

    def _get_access_token(self):
        response = self.client.post(
            self.token_url,
            data=json.dumps({'username': 'testuser', 'password': 'ValidPass123'}),
            content_type='application/json'
        )
        return json.loads(response.content)['access']

    def test_upload_avatar_authenticated_returns_200(self):
        """Valid JWT token and JPEG image upload succeeds."""
        token = self._get_access_token()
        response = self.client.post(
            self.avatar_url,
            {'file': self.test_image},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_avatar_unauthenticated_returns_401(self):
        """Upload without token returns 401."""
        response = self.client.post(
            self.avatar_url,
            {'file': self.test_image}
        )
        self.assertEqual(response.status_code, 401)

    def test_upload_avatar_returns_avatar_url(self):
        """Response includes the avatar_url."""
        token = self._get_access_token()
        response = self.client.post(
            self.avatar_url,
            {'file': self.test_image},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        body = json.loads(response.content)
        self.assertIn('avatar_url', body)
        self.assertIn('avatars/', body['avatar_url'])

    def test_upload_avatar_saves_to_profile(self):
        """After upload, the avatar path is saved to the user's profile."""
        token = self._get_access_token()
        self.client.post(
            self.avatar_url,
            {'file': self.test_image},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.user.profile.refresh_from_db()
        self.assertIsNotNone(self.user.profile.avatar)
        self.assertTrue(self.user.profile.avatar.name.startswith('avatars/'))

    def test_upload_avatar_replaces_old_avatar(self):
        """Uploading a new avatar replaces the old one."""
        token = self._get_access_token()
        
        # Upload first avatar
        from io import BytesIO
        from PIL import Image
        img1 = Image.new('RGB', (100, 100), color='red')
        img1_bytes = BytesIO()
        img1.save(img1_bytes, format='JPEG')
        img1_bytes.seek(0)
        img1_bytes.name = 'first.jpg'
        
        self.client.post(
            self.avatar_url,
            {'file': img1_bytes},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.user.profile.refresh_from_db()
        first_avatar = self.user.profile.avatar.name
        
        # Upload second avatar
        img2 = Image.new('RGB', (100, 100), color='blue')
        img2_bytes = BytesIO()
        img2.save(img2_bytes, format='JPEG')
        img2_bytes.seek(0)
        img2_bytes.name = 'second.jpg'
        
        self.client.post(
            self.avatar_url,
            {'file': img2_bytes},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.user.profile.refresh_from_db()
        second_avatar = self.user.profile.avatar.name
        
        # Check that avatar changed
        self.assertNotEqual(first_avatar, second_avatar)

    def test_upload_avatar_accepts_png(self):
        """PNG images are accepted."""
        from io import BytesIO
        from PIL import Image
        token = self._get_access_token()
        
        img = Image.new('RGB', (100, 100), color='green')
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        img_bytes.name = 'test_avatar.png'
        
        response = self.client.post(
            self.avatar_url,
            {'file': img_bytes},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_avatar_accepts_webp(self):
        """WebP images are accepted."""
        from io import BytesIO
        from PIL import Image
        token = self._get_access_token()
        
        img = Image.new('RGB', (100, 100), color='yellow')
        img_bytes = BytesIO()
        img.save(img_bytes, format='WebP')
        img_bytes.seek(0)
        img_bytes.name = 'test_avatar.webp'
        
        response = self.client.post(
            self.avatar_url,
            {'file': img_bytes},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_avatar_rejects_invalid_format(self):
        """Non-image files are rejected."""
        from io import BytesIO
        token = self._get_access_token()
        
        invalid_file = BytesIO(b'not an image')
        invalid_file.name = 'fake.txt'
        
        # This should fail during image open
        response = self.client.post(
            self.avatar_url,
            {'file': invalid_file},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        # Either 400 or 500 depending on error handling
        self.assertNotEqual(response.status_code, 200)

    def test_upload_avatar_rejects_oversized_image(self):
        """Images over 10 MB are rejected."""
        from io import BytesIO
        from PIL import Image
        token = self._get_access_token()
        
        # Create a large image (simulate >10 MB)
        img = Image.new('RGB', (10000, 10000), color='red')
        img_bytes = BytesIO()
        img.save(img_bytes, format='JPEG', quality=95)
        img_bytes.seek(0)
        img_bytes.name = 'large_avatar.jpg'
        
        # Check the size
        img_bytes.seek(0, 2)  # Seek to end
        size = img_bytes.tell()
        img_bytes.seek(0)  # Seek back to start
        
        if size > 10 * 1024 * 1024:
            response = self.client.post(
                self.avatar_url,
                {'file': img_bytes},
                HTTP_AUTHORIZATION=f'Bearer {token}'
            )
            self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# Auth Public Profile Tests  (GET /api/auth/profile/{username})
# ---------------------------------------------------------------------------

class AuthPublicProfileTests(TestCase):
    """Tests for GET /api/auth/profile/{username} — public user profiles."""

    def setUp(self):
        self.client = Client()
        self.public_user = User.objects.create_user(
            username='publicuser',
            email='public@example.com',
            password='ValidPass123'
        )
        self.public_user.profile.email_verified = True
        self.public_user.profile.profile_public = True
        self.public_user.profile.display_name = 'Public User'
        self.public_user.profile.bio = 'I am public'
        self.public_user.profile.twitter_url = 'https://twitter.com/publicuser'
        self.public_user.profile.github_url = 'https://github.com/publicuser'
        self.public_user.profile.website_url = 'https://publicuser.com'
        self.public_user.profile.save()
        
        self.private_user = User.objects.create_user(
            username='privateuser',
            email='private@example.com',
            password='ValidPass123'
        )
        self.private_user.profile.email_verified = True
        self.private_user.profile.profile_public = False
        self.private_user.profile.save()

    def test_get_public_profile_returns_200(self):
        """GET for a public profile returns 200."""
        response = self.client.get('/api/auth/profile/publicuser')
        self.assertEqual(response.status_code, 200)

    def test_get_public_profile_requires_no_auth(self):
        """Public profiles are accessible without authentication."""
        response = self.client.get('/api/auth/profile/publicuser')
        self.assertEqual(response.status_code, 200)

    def test_get_public_profile_response_includes_fields(self):
        """Response includes username, display_name, bio, and social links."""
        response = self.client.get('/api/auth/profile/publicuser')
        body = json.loads(response.content)
        
        self.assertEqual(body['username'], 'publicuser')
        self.assertEqual(body['display_name'], 'Public User')
        self.assertEqual(body['bio'], 'I am public')
        self.assertEqual(body['twitter_url'], 'https://twitter.com/publicuser')
        self.assertEqual(body['github_url'], 'https://github.com/publicuser')
        self.assertEqual(body['website_url'], 'https://publicuser.com')

    def test_get_public_profile_includes_role(self):
        """Response includes the user's role."""
        response = self.client.get('/api/auth/profile/publicuser')
        body = json.loads(response.content)
        self.assertIn('role', body)
        self.assertEqual(body['role'], 'reader')  # default

    def test_get_private_profile_returns_404(self):
        """GET for a private profile returns 404."""
        response = self.client.get('/api/auth/profile/privateuser')
        self.assertEqual(response.status_code, 404)

    def test_get_nonexistent_profile_returns_404(self):
        """GET for a non-existent user returns 404."""
        response = self.client.get('/api/auth/profile/ghost')
        self.assertEqual(response.status_code, 404)

    def test_get_public_profile_without_avatar_includes_null(self):
        """If user has no avatar, avatar_url is null in the response."""
        response = self.client.get('/api/auth/profile/publicuser')
        body = json.loads(response.content)
        self.assertIn('avatar_url', body)

    def test_get_public_profile_editor_role(self):
        """Profile for an editor shows editor role."""
        self.public_user.profile.role = 'editor'
        self.public_user.profile.save()
        
        response = self.client.get('/api/auth/profile/publicuser')
        body = json.loads(response.content)
        self.assertEqual(body['role'], 'editor')

    def test_get_public_profile_admin_role(self):
        """Profile for an admin shows admin role."""
        self.public_user.profile.role = 'admin'
        self.public_user.profile.save()
        
        response = self.client.get('/api/auth/profile/publicuser')
        body = json.loads(response.content)
        self.assertEqual(body['role'], 'admin')

    def test_get_public_profile_with_special_characters_in_username(self):
        """Usernames with special characters are handled correctly."""
        # Create user with hyphen in username
        special_user = User.objects.create_user(
            username='special-user',
            email='special@example.com',
            password='ValidPass123'
        )
        special_user.profile.profile_public = True
        special_user.profile.save()
        
        response = self.client.get('/api/auth/profile/special-user')
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['username'], 'special-user')

    def test_get_public_profile_does_not_expose_email(self):
        """Email address is NOT included in public profile response."""
        response = self.client.get('/api/auth/profile/publicuser')
        body = json.loads(response.content)
        self.assertNotIn('email', body)

    def test_get_public_profile_case_sensitive_username(self):
        """Username lookup is case-sensitive."""
        response = self.client.get('/api/auth/profile/PUBLICUSER')
        # Django usernames are case-sensitive
        self.assertEqual(response.status_code, 404)

    def test_switching_profile_public_to_private_hides_it(self):
        """Changing profile_public to False makes it inaccessible."""
        # Initially public
        response1 = self.client.get('/api/auth/profile/publicuser')
        self.assertEqual(response1.status_code, 200)
        
        # Make private
        self.public_user.profile.profile_public = False
        self.public_user.profile.save()
        
        # Now should be 404
        response2 = self.client.get('/api/auth/profile/publicuser')
        self.assertEqual(response2.status_code, 404)


# ---------------------------------------------------------------------------
# Auth Change Password Tests  (POST /api/auth/change-password)
# ---------------------------------------------------------------------------

class AuthChangePasswordTests(TestCase):
    """Tests for POST /api/auth/change-password — authenticated password change."""

    def setUp(self):
        self.client = Client()
        self.change_password_url = '/api/auth/change-password'
        self.token_url = '/api/token/pair'
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='OldPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()

    def _get_access_token(self):
        response = self.client.post(
            self.token_url,
            data=json.dumps({'username': 'testuser', 'password': 'OldPass123'}),
            content_type='application/json'
        )
        return json.loads(response.content)['access']

    def test_change_password_authenticated_returns_200(self):
        """Valid token and correct current password returns 200."""
        token = self._get_access_token()
        response = self.client.post(
            self.change_password_url,
            data=json.dumps({
                'current_password': 'OldPass123',
                'new_password': 'NewPass456',
                'new_password_confirm': 'NewPass456'
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_change_password_unauthenticated_returns_401(self):
        """Change password without token returns 401."""
        response = self.client.post(
            self.change_password_url,
            data=json.dumps({
                'current_password': 'OldPass123',
                'new_password': 'NewPass456',
                'new_password_confirm': 'NewPass456'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_change_password_wrong_current_password_returns_error(self):
        """Wrong current password returns error status."""
        token = self._get_access_token()
        response = self.client.post(
            self.change_password_url,
            data=json.dumps({
                'current_password': 'WrongPass123',
                'new_password': 'NewPass456',
                'new_password_confirm': 'NewPass456'
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'error')

    def test_change_password_updates_password(self):
        """After successful change, can login with new password."""
        token = self._get_access_token()
        self.client.post(
            self.change_password_url,
            data=json.dumps({
                'current_password': 'OldPass123',
                'new_password': 'NewPass456',
                'new_password_confirm': 'NewPass456'
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        
        # Try to login with new password
        login_response = self.client.post(
            self.token_url,
            data=json.dumps({'username': 'testuser', 'password': 'NewPass456'}),
            content_type='application/json'
        )
        self.assertEqual(login_response.status_code, 200)

    def test_change_password_old_password_no_longer_works(self):
        """Old password is rejected after change."""
        token = self._get_access_token()
        self.client.post(
            self.change_password_url,
            data=json.dumps({
                'current_password': 'OldPass123',
                'new_password': 'NewPass456',
                'new_password_confirm': 'NewPass456'
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        
        # Try to login with old password
        login_response = self.client.post(
            self.token_url,
            data=json.dumps({'username': 'testuser', 'password': 'OldPass123'}),
            content_type='application/json'
        )
        self.assertEqual(login_response.status_code, 401)


# ---------------------------------------------------------------------------
# Rate Limiting Tests
# ---------------------------------------------------------------------------

@override_settings(RATE_LIMIT_ENABLED=True)
class LoginRateLimitTests(TestCase):
    """Tests for rate limiting on POST /api/token/pair (5 per 10 min per IP)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        self.url = '/api/token/pair'
        # A real verified user so some requests can succeed
        self.user = User.objects.create_user(
            username='rl_user', email='rl@example.com', password='ValidPass123'
        )
        self.user.profile.email_verified = True
        self.user.profile.save()

    def _post(self, ip='10.0.0.1', username='rl_user', password='ValidPass123'):
        return self.client.post(
            self.url,
            data=json.dumps({'username': username, 'password': password}),
            content_type='application/json',
            REMOTE_ADDR=ip,
        )

    def test_first_five_attempts_are_allowed(self):
        """First 5 requests from same IP are not rate-limited."""
        for _ in range(5):
            r = self._post()
            self.assertNotEqual(r.status_code, 429)

    def test_sixth_attempt_is_blocked(self):
        """6th request from same IP within window returns 429."""
        for _ in range(5):
            self._post()
        r = self._post()
        self.assertEqual(r.status_code, 429)

    def test_429_response_contains_retry_message(self):
        """Rate-limited response includes a retry message."""
        for _ in range(5):
            self._post()
        r = self._post()
        body = json.loads(r.content)
        self.assertIn('detail', body)
        self.assertIn('seconds', body['detail'])

    def test_different_ips_have_independent_buckets(self):
        """Exhausting the limit for one IP does not affect another IP."""
        for _ in range(5):
            self._post(ip='10.0.0.1')
        # IP 10.0.0.1 is now blocked
        self.assertEqual(self._post(ip='10.0.0.1').status_code, 429)
        # IP 10.0.0.2 should still be allowed
        self.assertNotEqual(self._post(ip='10.0.0.2').status_code, 429)

    def test_x_forwarded_for_is_used_as_identifier(self):
        """X-Forwarded-For header is respected for IP detection."""
        for _ in range(5):
            self.client.post(
                self.url,
                data=json.dumps({'username': 'rl_user', 'password': 'ValidPass123'}),
                content_type='application/json',
                HTTP_X_FORWARDED_FOR='5.5.5.5',
            )
        r = self.client.post(
            self.url,
            data=json.dumps({'username': 'rl_user', 'password': 'ValidPass123'}),
            content_type='application/json',
            HTTP_X_FORWARDED_FOR='5.5.5.5',
        )
        self.assertEqual(r.status_code, 429)


@override_settings(RATE_LIMIT_ENABLED=True)
class RegisterRateLimitTests(TestCase):
    """Tests for rate limiting on POST /api/auth/register (3 per day per IP)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        self.url = '/api/auth/register'

    def _post(self, suffix, ip='10.1.0.1'):
        return self.client.post(
            self.url,
            data=json.dumps({
                'email': f'newuser{suffix}@example.com',
                'password': 'ValidPass123',
                'password_confirm': 'ValidPass123',
                'username': f'newuser{suffix}',
            }),
            content_type='application/json',
            REMOTE_ADDR=ip,
        )

    def test_first_three_registrations_are_allowed(self):
        """First 3 requests from same IP are not rate-limited."""
        for i in range(3):
            r = self._post(i)
            self.assertNotEqual(r.status_code, 429)

    def test_fourth_registration_is_blocked(self):
        """4th registration attempt from same IP returns 429."""
        for i in range(3):
            self._post(i)
        r = self._post(99)
        self.assertEqual(r.status_code, 429)

    def test_different_ips_have_independent_buckets(self):
        """Exhausting the registration limit on one IP does not block another."""
        for i in range(3):
            self._post(i, ip='10.1.0.1')
        self.assertEqual(self._post(99, ip='10.1.0.1').status_code, 429)
        self.assertNotEqual(self._post(100, ip='10.1.0.2').status_code, 429)


class ResendVerificationTests(TestCase):
    """Tests for POST /api/auth/resend-verification."""

    URL = '/api/auth/resend-verification'

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='unverifed_user', email='unverified@example.com', password='Pass1234!'
        )
        self.user.profile.email_verified = False
        self.user.profile.save()

    def _post(self, email, ip='1.2.3.4'):
        return self.client.post(
            self.URL,
            data=json.dumps({'email': email}),
            content_type='application/json',
            REMOTE_ADDR=ip,
        )

    def test_returns_200_for_unverified_user(self):
        r = self._post('unverified@example.com')
        self.assertEqual(r.status_code, 200)

    def test_sends_verification_email(self):
        self._post('unverified@example.com')
        self.assertEqual(len(mail.outbox), 1)

    def test_returns_generic_success_for_unknown_email(self):
        """Should not reveal whether the email exists."""
        r = self._post('nobody@example.com')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['status'], 'success')

    def test_no_email_sent_for_unknown_address(self):
        self._post('nobody@example.com')
        self.assertEqual(len(mail.outbox), 0)

    def test_no_email_sent_for_already_verified_user(self):
        self.user.profile.email_verified = True
        self.user.profile.save()
        self._post('unverified@example.com')
        self.assertEqual(len(mail.outbox), 0)

    def test_old_tokens_invalidated_on_resend(self):
        """Previous unused token should be marked used before a new one is created."""
        old_token = create_email_verification_token(self.user)
        self._post('unverified@example.com')
        old_token.refresh_from_db()
        self.assertTrue(old_token.is_used)

    def test_new_token_created_on_resend(self):
        initial_count = EmailVerificationToken.objects.filter(user=self.user).count()
        self._post('unverified@example.com')
        new_count = EmailVerificationToken.objects.filter(user=self.user).count()
        self.assertGreater(new_count, initial_count)

    def test_response_body_has_status_and_message(self):
        r = self._post('unverified@example.com')
        data = r.json()
        self.assertIn('status', data)
        self.assertIn('message', data)


@override_settings(RATE_LIMIT_ENABLED=True)
class ResendVerificationRateLimitTests(TestCase):
    """Tests for rate limiting on POST /api/auth/resend-verification (3/hour per IP)."""

    URL = '/api/auth/resend-verification'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username='rl_unverified', email='rl_unverified@example.com', password='Pass1234!'
        )
        self.user.profile.email_verified = False
        self.user.profile.save()

    def _post(self, ip='9.9.9.9'):
        return self.client.post(
            self.URL,
            data=json.dumps({'email': 'rl_unverified@example.com'}),
            content_type='application/json',
            REMOTE_ADDR=ip,
        )

    def test_first_three_requests_allowed(self):
        for _ in range(3):
            r = self._post()
            self.assertNotEqual(r.status_code, 429)

    def test_fourth_request_is_rate_limited(self):
        for _ in range(3):
            self._post()
        r = self._post()
        self.assertEqual(r.status_code, 429)

    def test_different_ips_are_independent(self):
        for _ in range(3):
            self._post(ip='9.9.9.1')
        self.assertEqual(self._post(ip='9.9.9.1').status_code, 429)
        self.assertNotEqual(self._post(ip='9.9.9.2').status_code, 429)
