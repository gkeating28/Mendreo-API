import traceback

from rest_framework.exceptions import APIException

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (Mail, Personalization, Email)

from ..utils import Api, Message, Constants, DateUtils

from ..user.models import User

import random, os

SendGrid = SendGridAPIClient(Api.SENDGRID_API_KEY)

HEADERS = {
    'Authorization': "Bearer {}".format(Api.SENDGRID_API_KEY),
    'Content-Type': "application/json"
}


class MailableException:

    message: str
    exception: Exception
    stack_trace: str

    def __init__(self, exception: Exception, message: str = None):
        self.exception = exception
        self.message = message
        self.stack_trace = traceback.format_exc()


def send_code(user_id):
    user = User.objects.get(id=user_id)
    user.verification_code = generate_random_number(4)
    user.verification_code_sent_at = DateUtils.now()
    user.save()

    mail = Mail(
        from_email=(Api.EMAIL_FROM, Constants.APP_NAME),
        to_emails=user.email,
        subject='Password Reset Request',
        html_content='Hi {},<br><br><b>{}</b> is your password reset code'.format(user.first_name, user.verification_code))

    _send_email(mail)


def send_account_verification_code(user_id):
    user = User.objects.get(id=user_id)
    user.verification_code = generate_random_number(4)
    user.verification_code_sent_at = DateUtils.now()
    user.save()

    mail = Mail(
        from_email=(Api.EMAIL_FROM, Constants.APP_NAME),
        to_emails=user.email,
        subject='Account Verification',
        html_content='Hi {},<br><br><b>{}</b> is your account verification code'.format(user.first_name, user.verification_code))

    _send_email(mail)


def send_developer_errors(body: str, subject: str = "System Error", mailable_exceptions: [MailableException] = None):

    if mailable_exceptions:
        body += "\n\nErrors:\n\n"
        for mailable_exception in mailable_exceptions:
            body += f"Exception: {mailable_exception.exception}\n"
            body += f"Stack Trace: {mailable_exception.stack_trace}\n"

    message = Mail(
        from_email=Api.EMAIL_FROM,
        to_emails=Constants.DEVELOPERS,
        subject=subject,
        html_content=body
    )

    _send_email(message)


def generate_random_number(length):
    return int(''.join([str(random.randint(1, 9)) for _ in range(length)]))


def _send_email(mail):

    try:
        SendGrid.send(mail)
    except Exception as e:
        if not os.environ["GENERA_DEBUG"] == "True":
            print(f"error while sending email with content: {mail.content}", e)
        raise APIException(Message.create(e))
