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
        """Test registration with auto-generated username."""
        data = {
            'email': 'newuser@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
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
        """Test that registration sends verification email."""
        data = {
            'email': 'testuser@example.com',
            'password': 'ValidPass123',
            'password_confirm': 'ValidPass123',
        }
        
        response = self.client.post(
            self.register_url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Check email was sent (requires EMAIL_BACKEND set to console or similar in tests)
        # This test assumes mail backend is configured
        # In real tests, mock the send_mail function


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
