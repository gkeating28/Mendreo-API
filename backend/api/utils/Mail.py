import traceback

from rest_framework.exceptions import APIException

import resend

from ..utils import Api, Message, Constants, DateUtils

from ..user.models import User

import random, os


class MailableException:

    message: str
    exception: Exception
    stack_trace: str

    def __init__(self, exception: Exception, message: str = None):
        self.exception = exception
        self.message = message
        self.stack_trace = traceback.format_exc()


def _named_from() -> str:
    return f"{Constants.APP_NAME} <{Api.EMAIL_FROM}>"


def send_code(user_id):
    user = User.objects.get(id=user_id)
    user.verification_code = generate_random_number(4)
    user.verification_code_sent_at = DateUtils.now()
    user.save()

    _send_email({
        "from": _named_from(),
        "to": user.email,
        "subject": "Password Reset Request",
        "html": "Hi {},<br><br><b>{}</b> is your password reset code".format(
            user.first_name, user.verification_code
        ),
    })


def send_account_verification_code(user_id):
    user = User.objects.get(id=user_id)
    user.verification_code = generate_random_number(4)
    user.verification_code_sent_at = DateUtils.now()
    user.save()

    _send_email({
        "from": _named_from(),
        "to": user.email,
        "subject": "Account Verification",
        "html": "Hi {},<br><br><b>{}</b> is your account verification code".format(
            user.first_name, user.verification_code
        ),
    })


def send_trust_and_safety_alert(session_id: str):
    from ..setting.models import Setting
    from ..session.models import Session

    address = Setting.get_trust_and_safety_email()
    if not address:
        return

    session = Session.objects.filter(id=session_id).select_related("consumer").first()
    consumer_id = session.consumer_id if session else "unknown"
    _send_email({
        "from": _named_from(),
        "to": address,
        "subject": "High-risk session needs review",
        "html": (
            "A session was flagged high risk and needs a Trust and Safety review.<br><br>"
            f"Session: {session_id}<br>"
            f"Consumer: {consumer_id}<br><br>"
            "The message text is not included in this email. Open the session in the admin console."
        ),
    })


def send_developer_errors(body: str, subject: str = "System Error", mailable_exceptions: [MailableException] = None):

    if mailable_exceptions:
        body += "\n\nErrors:\n\n"
        for mailable_exception in mailable_exceptions:
            body += f"Exception: {mailable_exception.exception}\n"
            body += f"Stack Trace: {mailable_exception.stack_trace}\n"

    _send_email({
        "from": Api.EMAIL_FROM,
        "to": Constants.DEVELOPERS,
        "subject": subject,
        "html": body,
    })


def generate_random_number(length):
    return int(''.join([str(random.randint(1, 9)) for _ in range(length)]))


def _recipients(to) -> list:
    if isinstance(to, str):
        return [to]
    return list(to)


def _send_email(mail: dict):
    # Set at send time so an empty key fails here, the same way an empty
    # SendGrid key failed inside SendGrid.send, and not at import.
    resend.api_key = Api.RESEND_API_KEY or ""

    try:
        resend.Emails.send({
            "from": mail["from"],
            "to": _recipients(mail["to"]),
            "subject": mail["subject"],
            "html": mail["html"],
        })
    except Exception as e:
        if not os.environ.get("GENERAL_DEBUG", "False") == "True":
            print(f"error while sending email with content: {mail['html']}", e)
        raise APIException(Message.create(e))
