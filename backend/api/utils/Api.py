import os

# Object storage: Supabase Storage.
# Browser uploads use native REST signed upload URLs (see api/utils/File.py).
# S3-compatible credentials remain for fallbacks / private chat-log helpers.
# https://supabase.com/docs/guides/storage/uploads/standard-uploads
#
# SUPABASE_STORAGE_URL      e.g. https://<project_ref>.supabase.co
#                           (used to build public object + image-render URLs)
# SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY
#                           REST signed uploads + object write/exists/delete
# SUPABASE_STORAGE_S3_ENDPOINT  e.g. https://<project_ref>.storage.supabase.co/storage/v1/s3
#                           (optional boto3 fallback; S3 access keys under
#                           Project Settings -> Storage -> S3 Access Keys)
def _default_storage_s3_endpoint(storage_url: str) -> str:
    """Derive https://<ref>.storage.supabase.co/storage/v1/s3 from
    https://<ref>.supabase.co, so only SUPABASE_STORAGE_URL needs setting in
    the common case. Falls back to an obviously-fake (but URL-shaped)
    placeholder if nothing is configured at all -- boto3.client() raises
    ValueError on a truly empty/invalid endpoint string, which would crash
    the whole app at import time (every view chain imports through
    api/image/serializers.py -> this module) rather than only failing the
    specific request that actually tries to touch storage.
    """
    if not storage_url:
        return "https://storage-not-configured.invalid/storage/v1/s3"
    scheme, _, rest = storage_url.partition("://")
    host, _, _ = rest.partition("/")
    ref, dot, domain = host.partition(".")
    if not dot:
        return f"{scheme}://{host}/storage/v1/s3"
    return f"{scheme}://{ref}.storage.{domain}/storage/v1/s3"


SUPABASE_STORAGE_URL = os.environ.get("SUPABASE_STORAGE_URL", "").rstrip("/")
SUPABASE_STORAGE_S3_ENDPOINT = os.environ.get("SUPABASE_STORAGE_S3_ENDPOINT") or _default_storage_s3_endpoint(SUPABASE_STORAGE_URL)
SUPABASE_STORAGE_ACCESS_KEY_ID = os.environ.get("SUPABASE_STORAGE_ACCESS_KEY_ID", "")
SUPABASE_STORAGE_SECRET_ACCESS_KEY = os.environ.get("SUPABASE_STORAGE_SECRET_ACCESS_KEY", "")
# Must match the region shown in Supabase → Storage → S3 (for this project:
# eu-west-1). A wrong region produces SignatureDoesNotMatch on every PUT.
SUPABASE_STORAGE_REGION = os.environ.get("SUPABASE_STORAGE_REGION", "eu-west-1")
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "")
# Supabase Storage sets public/private per BUCKET, not per object (unlike S3
# ACLs). Chat logs contain consumer PII and must never be publicly readable,
# so they go in a separate bucket created as "private" in the Supabase
# dashboard. Defaults to the main bucket if unset, but that only stays
# private if SUPABASE_STORAGE_BUCKET itself is also private (i.e. don't use
# a public bucket for both unless you don't set this).
SUPABASE_STORAGE_PRIVATE_BUCKET = os.environ.get("SUPABASE_STORAGE_PRIVATE_BUCKET", SUPABASE_STORAGE_BUCKET)

# Used for native Supabase Storage REST signed uploads (preferred over S3
# presigns). Service role bypasses RLS; anon works when public-bucket write
# policies exist (see storage migration mendreo_public_*).
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "") or os.environ.get("SUPABASE_KEY", "")
# Anon keys are public by design. Bootstrap this project's deploy if unset so
# Content Editor uploads work without a new Vercel env var. Prefer setting
# SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) explicitly in production.
if not SUPABASE_ANON_KEY and "spoiyfwfrhplzmqhqlsu" in (SUPABASE_STORAGE_URL or ""):
    SUPABASE_ANON_KEY = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNwb2l5ZndmcmhwbHptcWhxbHN1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM2OTM1MzcsImV4cCI6MjA5OTI2OTUzN30."
        "77T4JhPmYrqyPzCjOxNTsnAW5IPJoJXGAWJ4MwFigvU"
    )

# Legacy AWS S3 credentials — kept only so `scripts/migrate_s3_to_supabase.py`
# (a one-off command) can read the old bucket during migration. Not used for
# any application read/write path; safe to leave unset once migration is done.
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

EMAIL_FROM = os.environ.get("EMAIL_FROM", "noreply@example.com")

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")

# Temporary: skip Stripe/Apple/Google payment requirements. When true,
# consumers get a complimentary active subscription (no payment row) so the
# web/mobile clients can skip the paywall. Turn off once billing is wired up.
# Accepted values: 1/true/yes (case-insensitive).
BYPASS_SUBSCRIPTION = os.environ.get("BYPASS_SUBSCRIPTION", "").lower() in ("1", "true", "yes")

BUNDLE_ID_IOS = os.environ.get("BUNDLE_ID_IOS", "")
BUNDLE_ID_ANDROID = os.environ.get("BUNDLE_ID_ANDROID", "")

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
APPLE_IN_APP_SHARED_SECRET = os.environ.get("APPLE_IN_APP_SHARED_SECRET", "")

SURVEY_CODE = os.environ.get("SURVEY_CODE", "")
SURVEY_WEB_APP_URL = os.environ.get("SURVEY_WEB_APP_URL", "")
SURVEY_MOBILE_APP_URL = os.environ.get("SURVEY_MOBILE_APP_URL", "")
