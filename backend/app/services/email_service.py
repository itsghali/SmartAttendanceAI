import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config.settings import get_settings

logger = logging.getLogger("app.email")


class EmailBackend(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailBackend:
    """Writes emails to the application log. Used when SMTP isn't configured (local dev)."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("EMAIL to=%s subject=%r body=%r", to, subject, body)


class SMTPEmailBackend:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        from_email: str,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._from_email = from_email

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self._host, self._port) as smtp:
            if self._use_tls:
                smtp.starttls()
            if self._username and self._password:
                smtp.login(self._username, self._password)
            smtp.send_message(message)


def get_email_backend() -> EmailBackend:
    settings = get_settings()
    if settings.smtp_host:
        return SMTPEmailBackend(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            from_email=settings.from_email,
        )
    return ConsoleEmailBackend()


class EmailService:
    def __init__(self, backend: EmailBackend | None = None):
        self._backend = backend or get_email_backend()

    def send_otp_email(self, to: str, code: str, purpose: str) -> None:
        subject = {
            "email_verification": "Verify your SmartAttendanceAI account",
            "password_reset": "Reset your SmartAttendanceAI password",
        }.get(purpose, "Your SmartAttendanceAI verification code")
        body = f"Your verification code is {code}. It expires in 10 minutes."
        self._backend.send(to, subject, body)

    def send_workforce_intelligence_alert(self, to: str, subject: str, body: str) -> None:
        self._backend.send(to, subject, body)
