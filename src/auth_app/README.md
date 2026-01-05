# Authentication App (auth_app) - Setup Guide

This guide helps you set up and test the new authentication features implemented on December 31, 2025.

## Quick Start

### 1. Apply Database Migrations

```bash
cd /home/achilles/Documents/blog/backend
python manage.py migrate auth_app
```

This creates three new tables:
- `auth_app_emailverificationtoken`
- `auth_app_passwordresettoken`
- `auth_app_userprofile`

### 2. Configure Environment Variables (Development)

Add these to your `.env` file in `/home/achilles/Documents/blog/backend/`:

```bash
# Email Configuration (Development - console output)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=localhost
EMAIL_PORT=1025
EMAIL_USE_TLS=false
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=noreply@gardenblog.com

# Frontend URL (used in email links)
FRONTEND_URL=http://localhost:3000
```

**Note**: In development, emails are printed to console. To test email sending with a real SMTP server, use:

```bash
# Gmail (requires app-specific password)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
```

### 3. Run Tests

```bash
cd /home/achilles/Documents/blog/backend
python manage.py test auth_app
```

Expected output: All ~50 tests should pass

### 4. Create Django Admin User (Optional)

```bash
cd /home/achilles/Documents/blog/backend
python manage.py createsuperuser
```

Then visit: http://localhost:8000/admin/

## API Endpoints

### Register New User
```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newuser@example.com",
    "password": "SecurePass123",
    "password_confirm": "SecurePass123",
    "username": "newuser"
  }'
```

**Response** (Success):
```json
{
  "status": "success",
  "message": "User registered successfully. Please check your email to verify your account.",
  "user": {
    "id": 1,
    "username": "newuser",
    "email": "newuser@example.com",
    "email_verified": false
  }
}
```

### Verify Email
```bash
# Get token from console output when EMAIL_BACKEND is console
curl -X POST http://localhost:8000/api/auth/verify-email/ \
  -H "Content-Type: application/json" \
  -d '{
    "token": "PASTE_TOKEN_HERE"
  }'
```

### Request Password Reset
```bash
curl -X POST http://localhost:8000/api/auth/password-reset-request/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newuser@example.com"
  }'
```

### Confirm Password Reset
```bash
# Get token from console output
curl -X POST http://localhost:8000/api/auth/password-reset-confirm/ \
  -H "Content-Type: application/json" \
  -d '{
    "token": "PASTE_TOKEN_HERE",
    "new_password": "NewSecurePass456",
    "new_password_confirm": "NewSecurePass456"
  }'
```

## Admin Interface

The Django admin interface includes pages for managing tokens:

1. **Email Verification Tokens**
   - View all tokens
   - See expiration dates
   - Check if token was used
   - Delete expired tokens

2. **Password Reset Tokens**
   - Same functionality as email verification tokens

3. **User Profiles**
   - View email verification status
   - See created/updated timestamps

Visit: http://localhost:8000/admin/

## Testing Workflow

### Manual Test Scenario

1. **Register user**:
   ```bash
   curl -X POST http://localhost:8000/api/auth/register/ \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com", "password": "TestPass123", "password_confirm": "TestPass123"}'
   ```

2. **Check console for verification email** (if using console backend)

3. **Copy token from email**

4. **Verify email**:
   ```bash
   curl -X POST http://localhost:8000/api/auth/verify-email/ \
     -H "Content-Type: application/json" \
     -d '{"token": "TOKEN_HERE"}'
   ```

5. **Request password reset**:
   ```bash
   curl -X POST http://localhost:8000/api/auth/password-reset-request/ \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com"}'
   ```

6. **Confirm password reset**:
   ```bash
   curl -X POST http://localhost:8000/api/auth/password-reset-confirm/ \
     -H "Content-Type: application/json" \
     -d '{"token": "RESET_TOKEN_HERE", "new_password": "NewPass456", "new_password_confirm": "NewPass456"}'
   ```

### Automated Tests

Run all tests:
```bash
python manage.py test auth_app
```

Run specific test class:
```bash
python manage.py test auth_app.tests.RegistrationTests
python manage.py test auth_app.tests.EmailVerificationTests
python manage.py test auth_app.tests.PasswordResetTests
python manage.py test auth_app.tests.TokenModelTests
```

Run single test:
```bash
python manage.py test auth_app.tests.RegistrationTests.test_register_success
```

## Files Structure

```
auth_app/
├── models.py                    # Database models
├── serializers.py               # Pydantic validators
├── api.py                       # API endpoints
├── utils.py                     # Helper functions
├── signals.py                   # Django signals
├── admin.py                     # Django admin config
├── tests.py                     # Unit tests (50+ tests)
├── apps.py                      # App config
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py
└── templates/auth_app/
    ├── verify_email.html
    └── password_reset.html
```

## Security Considerations

1. **Password Validation**:
   - Minimum 8 characters
   - Requires uppercase letter
   - Requires lowercase letter
   - Requires digit
   - Checked against common passwords
   - Checked against user attributes

2. **Token Security**:
   - 32-byte cryptographic random tokens
   - Single-use enforcement
   - 24-hour expiration
   - Indexed for fast lookups

3. **Email Security**:
   - Same message for existing/non-existing users (prevents email enumeration)
   - All tokens are temporary and single-use

4. **Database Security**:
   - Passwords hashed with Django's PBKDF2
   - Tokens stored securely (can't reverse engineer)

## Troubleshooting

### Migrations Not Applied
```bash
python manage.py showmigrations auth_app
python manage.py migrate auth_app
```

### Email Not Sending
1. Check EMAIL_BACKEND is set correctly
2. Check FRONTEND_URL is set to your frontend domain
3. Check DEFAULT_FROM_EMAIL is set
4. Look in Django shell for email output (if console backend)

### Tests Failing
1. Ensure migrations are applied
2. Check database is SQLite (development)
3. Verify Python version 3.9+ (for f-strings)

## Next Steps

### Frontend Implementation Needed:
1. Create `/register` page
2. Create `/verify-email` page with token from URL
3. Create `/forgot-password` page
4. Create `/reset-password` page with token from URL
5. Add Next.js API route handlers to forward requests to Django

### Production Deployment:
1. Configure real email backend (Gmail, SendGrid, etc.)
2. Set FRONTEND_URL to production domain
3. Update CORS_ALLOWED_ORIGINS
4. Enable DEBUG=false
5. Set DJANGO_SECRET_KEY securely
6. Configure database (PostgreSQL recommended)

## Documentation

For more details, see:
- [AUTH_IMPLEMENTATION_UPDATE.md](../AUTH_IMPLEMENTATION_UPDATE.md) - Full implementation details
- [AUTH_WORKFLOW.md](../AUTH_WORKFLOW.md) - Complete workflow diagrams
- [SYSTEM_STATUS.md](../SYSTEM_STATUS.md) - System status and architecture
