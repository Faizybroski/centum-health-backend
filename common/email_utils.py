import aiosmtplib
from email.message import EmailMessage
from common.config import settings
from common.config import logger
from email.utils import formataddr


async def send_email(to_email: str, subject: str, html_content: str):
    msg = EmailMessage()
    msg["From"] = formataddr((settings.EMAIL_FROM_NAME, settings.EMAIL_FROM))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content("Please view this email in an HTML-compatible client.")
    msg.add_alternative(html_content, subtype="html")
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.EMAIL_HOST,
            port=settings.EMAIL_PORT,
            username=settings.EMAIL_USERNAME,
            password=settings.EMAIL_PASSWORD,
            start_tls=True
        )
        logger.info("Email sent successfully.")
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise Exception(f"Could not send email: {e}")


async def custom_send_email(
    from_email: str,
    to_email: str,
    subject: str,
    html_content: str,
    bcc: str | list[str] = None,
    reply_to: str = None,
):
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.set_content("Please view this email in an HTML-compatible client.")
    msg.add_alternative(html_content, subtype="html")

    # Collect recipients (To + Bcc)
    recipients = [to_email]
    if bcc:
        if isinstance(bcc, str):
            bcc = [bcc]
        recipients.extend(bcc)

    try:
        await aiosmtplib.send(
            msg,
            recipients=recipients,
            hostname=settings.EMAIL_HOST,
            port=settings.EMAIL_PORT,
            username=settings.EMAIL_USERNAME,
            password=settings.EMAIL_PASSWORD,
            start_tls=True,
        )
        logger.info("Email sent successfully.")
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise Exception(f"Could not send email: {e}")
