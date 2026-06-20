# Django DEBUG Settings Management

This project now uses environment-based DEBUG configuration for better security and deployment flexibility.

## Current Configuration

The DEBUG setting is now controlled by the `DJANGO_DEBUG` environment variable:

- **Development (Default)**: `DEBUG = True`
- **Production**: `DEBUG = False`

## How to Use

### Method 1: Using the Management Script

```bash
# For Development (DEBUG=True)
python manage_debug.py dev

# For Production (DEBUG=False)
python manage_debug.py prod
```

### Method 2: Setting Environment Variable Directly

#### Windows (Command Prompt)
```cmd
# Development
set DJANGO_DEBUG=True
python manage.py runserver

# Production
set DJANGO_DEBUG=False
python manage.py runserver
```

#### Windows (PowerShell)
```powershell
# Development
$env:DJANGO_DEBUG="True"
python manage.py runserver

# Production
$env:DJANGO_DEBUG="False"
python manage.py runserver
```

#### Linux/Mac
```bash
# Development
export DJANGO_DEBUG=True
python manage.py runserver

# Production
export DJANGO_DEBUG=False
python manage.py runserver
```

## What Changes Based on DEBUG Setting

### When DEBUG=True (Development):
- ✅ Detailed error pages with traceback
- ✅ Auto-reload on code changes
- ✅ Development server features
- ✅ ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']
- ✅ Console logging

### When DEBUG=False (Production):
- ✅ Generic error pages (no sensitive information)
- ❌ No detailed error tracebacks
- ❌ No auto-reload
- ✅ Enhanced security settings
- ✅ ALLOWED_HOSTS = ['your-domain.com', 'www.your-domain.com']
- ✅ File-based logging to `logs/django.log`
- ✅ SSL/HTTPS security headers
- ✅ Secure cookies

## Security Features in Production

When `DEBUG=False`, the following security features are automatically enabled:

- `SECURE_BROWSER_XSS_FILTER = True`
- `SECURE_CONTENT_TYPE_NOSNIFF = True`
- `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`
- `SECURE_HSTS_SECONDS = 31536000`
- `SECURE_SSL_REDIRECT = True`
- `SESSION_COOKIE_SECURE = True`
- `CSRF_COOKIE_SECURE = True`
- `X_FRAME_OPTIONS = 'DENY'`

## Important Notes

1. **Always restart your Django server** after changing the DEBUG setting
2. **Update ALLOWED_HOSTS** in production with your actual domain names
3. **Keep DEBUG=False in production** for security
4. **Use DEBUG=True only during development**

## Troubleshooting

If you see the error "You're seeing this error because you have DEBUG = True", it means:
- You're in development mode (which is fine for development)
- The error has been fixed and you should see the actual page now

To switch to production mode:
```bash
python manage_debug.py prod
# Then restart your server
``` 