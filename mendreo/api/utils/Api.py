import os

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_CLOUD_FRONT_DOMAIN = os.environ.get("AWS_CLOUD_FRONT_DOMAIN", "")
AWS_CLOUD_FRONT_RESIZER_DOMAIN = os.environ.get("AWS_CLOUD_FRONT_RESIZER_DOMAIN", "")

EMAIL_FROM = os.environ.get("EMAIL_FROM", "noreply@example.com")

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")

BUNDLE_ID_IOS = os.environ.get("BUNDLE_ID_IOS", "")
BUNDLE_ID_ANDROID = os.environ.get("BUNDLE_ID_ANDROID", "")

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
APPLE_IN_APP_SHARED_SECRET = os.environ.get("APPLE_IN_APP_SHARED_SECRET", "")

SURVEY_CODE = os.environ.get("SURVEY_CODE", "")
SURVEY_WEB_APP_URL = os.environ.get("SURVEY_WEB_APP_URL", "")
SURVEY_MOBILE_APP_URL = os.environ.get("SURVEY_MOBILE_APP_URL", "")
