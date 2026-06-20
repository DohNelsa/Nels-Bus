# GARANTI EXPRESS Deployment Checklist (Render)

Use this runbook before each production release.

## 1) Required Environment Variables

Set these in Render service **Environment**.

### Core Django
- `DEPLOYMENT_ENV=production`
- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY=<strong-random-secret>`
- `ALLOWED_HOSTS=.onrender.com,<your-custom-domain-if-any>`
- `CSRF_TRUSTED_ORIGINS=https://*.onrender.com,https://<your-custom-domain-if-any>`

### Email
- `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
- `EMAIL_HOST=smtp.gmail.com`
- `EMAIL_PORT=587`
- `EMAIL_USE_TLS=True`
- `EMAIL_HOST_USER=<your-email>`
- `EMAIL_HOST_PASSWORD=<app-password>`
- `DEFAULT_FROM_EMAIL=<sender-email>`

### Branding
- `COMPANY_NAME=GARANTI EXPRESS`
- `COMPANY_SUPPORT_PHONE=+237675315422`
- `COMPANY_SUPPORT_EMAIL=<support-email>`
- `PUBLIC_SITE_URL=https://<your-render-service>.onrender.com`

### SMS / Twilio
- `SMS_ENABLED=true`
- `SMS_PROVIDER=twilio`
- `TWILIO_ACCOUNT_SID=AC...`
- `TWILIO_AUTH_TOKEN=...`
- `TWILIO_PHONE_NUMBER=+1...` (Twilio SMS-enabled number)

## 2) Deploy

### Database migrations (do not skip)

If PostgreSQL is linked but migrations never ran, **only static pages** (like the home page) may work. Any view that queries the database—**Book Rides** and **Routes** included—will return **500** (`ProgrammingError: relation does not exist`).

The **Start Command** must apply migrations before Gunicorn. The repo `Procfile` and `render.yaml` use:

```text
python manage.py migrate --noinput && gunicorn Nelsaproject.wsgi:application
```

If your Render service **Start Command** was set manually to only `gunicorn ...`, change it to the line above (or redeploy using this repo’s `Procfile`).

1. Push latest code to `main` (or your deployment branch).
2. Trigger deploy in Render.
3. Wait for successful build and startup.

## 3) Post-Deploy Health Checks

### App checks
- Home page loads
- Login works
- Booking page loads seats

### Booking flow checks
1. User books seats.
2. User verifies payment.
3. Admin confirms booking.
4. Check:
   - booking status becomes `Confirmed`
   - SMS status becomes `SENT`
   - receipt code exists

### SMS dashboard checks
- Open `/admin-sms/`
- Confirm:
  - Sent count increments
  - No unexpected spikes in failed count

### Receipt verification checks
- Open `/sms-receipt-verify/`
- Enter receipt code from SMS
- Confirm returned details match booking

## 4) Twilio Failure Troubleshooting

Use `/admin-sms/` error column first.

Common causes:
- Missing env vars (`SID`, `AUTH_TOKEN`, `PHONE_NUMBER`)
- Twilio trial recipient not verified
- Invalid sender/recipient format
- Sender not SMS-capable
- Invalid SID/token pair

Then retry from:
- per-booking action (`Resend SMS Receipt`)
- bulk action (`Retry All Failed`)

## 5) Security Checks

- Ensure no secrets are committed to repo.
- Rotate credentials if a secret was exposed.
- Confirm `DJANGO_SECRET_KEY` is set (not fallback value).

## 6) Rollback Plan

If release causes critical failure:
1. Roll back Render service to previous working deploy.
2. Re-check env vars (especially Twilio and email).
3. Re-run smoke tests.
4. Re-deploy fix in a controlled window.

## 7) Release Sign-Off

Release is done only when:
- [ ] Build succeeded
- [ ] Booking flow passed
- [ ] Admin confirm path passed
- [ ] SMS sent and verifiable
- [ ] No critical errors in logs/dashboard

