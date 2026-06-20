# Operations runbook (Nelsa / GARANTI EXPRESS)

## 1) Production data-layer baseline

- **Mandatory for production/staging:** PostgreSQL via `DATABASE_URL`.
- **Guardrail in code:** app startup fails in production/staging if DB is still SQLite.
- **Recommended deployment vars:** `DB_CONN_MAX_AGE=60`, `DB_SSLMODE=require` (or provider default).
- **Dependency:** `psycopg[binary]` is included in requirements.

## 2) Health, metrics, and dashboard inputs

- **Liveness:** `GET /health/`
- **Readiness:** `GET /health/ready/`
- **Metrics JSON:** `GET /internal/metrics/`
  - Access by `X-Metrics-Token` / `?token=` (`METRICS_AUTH_TOKEN`) or staff with webhook permission.
  - Includes:
    - webhook status counts (24h)
    - dead-letter webhook count
    - SMS failed total
    - notification queue backlog
    - pending booking groups

## 3) Alert policy and escalation

### Threshold variables

- `ALERT_WEBHOOK_REJECTED_THRESHOLD_5M` (default `3`)
- `ALERT_WEBHOOK_DEAD_LETTER_THRESHOLD` (default `1`)
- `ALERT_SMS_FAILED_THRESHOLD` (default `20`)
- `ALERT_PENDING_BOOKINGS_THRESHOLD` (default `100`)

### Ownership / escalation variables

- `ONCALL_OWNER` (default `ops-team`)
- `ALERT_EMAIL_RECIPIENTS` (primary)
- `ALERT_ESCALATION_RECIPIENTS` (secondary)

### Command to evaluate policy

- `python manage.py check_ops_alerts`
  - Sends alert email when any threshold is breached.
  - Intended schedule: every 5 minutes.

## 4) Incident tooling

### Safe webhook replay / dead-letter handling

- **Auto retry path:** webhook failures increment retry count and dead-letter when max retries reached.
- **Manual admin retry button:** in webhook detail page for non-dead-lettered events.
- **Bulk CLI retry:**  
  - `python manage.py retry_failed_webhooks --limit 100`

### Audit export

- `python manage.py export_audit_log --output ./exports/audit-$(date +%Y%m%d).csv --limit 10000`

### Refund reconciliation report

- `python manage.py refund_reconciliation_report --output ./exports/refund-recon-$(date +%Y%m%d).csv`

## 5) Async side effects queue

- Booking confirm now queues jobs instead of sending inline.
- Worker command:
  - `python manage.py process_notification_jobs --limit 100`
- Schedule this command every minute in production.

## 6) Backup and restore operations

### Backup

- `python manage.py backup_database --output-dir ./backups`
- Produces timestamped folder with:
  - `dumpdata.json` (portable logical backup)
  - sqlite file copy (when engine is sqlite)

### Restore

- `python manage.py restore_database --input ./backups/<timestamp>/dumpdata.json --flush --yes-i-know`

### Restore drill cadence

- **Weekly:** run backup command and verify artifact integrity.
- **Monthly drill (required):**
  1. Restore latest backup into a non-production environment.
  2. Run `python manage.py check`.
  3. Verify:
     - can log in as admin
     - webhook dashboard loads
     - audit export works
     - refund reconciliation report generates
  4. Record drill date, operator, duration, and issues.

## 7) On-call run checklist

1. Confirm `/health/ready/`.
2. Fetch `/internal/metrics/`.
3. Run `python manage.py check_ops_alerts`.
4. If webhooks failing:
   - inspect admin webhook events
   - run `retry_failed_webhooks`
   - escalate if dead-letter count remains above threshold.
5. If queue backlog high:
   - run `process_notification_jobs`
   - verify provider credentials and outbound network.

## 8) Security/compliance guardrails

### Secrets hygiene enforcement

- Git ignore protects common local secret artifacts (`.env*`, credentials JSON, key/pem files).
- Local commit scanner hook file is included at `.githooks/pre-commit`.
- Enable hooks once per clone:
  - `git config core.hooksPath .githooks`
- Manual/CI scan command:
  - `python manage.py scan_secrets --path .`

### Public endpoint abuse controls

- Rate limits (per IP, per minute):
  - `VERIFY_TICKET_RATE_LIMIT_PER_MIN`
  - `VERIFY_SMS_RECEIPT_RATE_LIMIT_PER_MIN`
  - `PAYMENT_WEBHOOK_RATE_LIMIT_PER_MIN`
- Optional webhook IP allowlist:
  - `PAYMENT_WEBHOOK_TRUSTED_IPS` (comma-separated)

### Expanded audit coverage

- Permission denials are now logged as `access_denied`.
- Sensitive user role/status actions are logged:
  - `user_make_staff`, `user_remove_staff`, `user_activate`, `user_deactivate`.
