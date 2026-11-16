"""Email notifications for password resets.

- Provider-neutral SMTP abstraction using stdlib smtplib ($0 cost).
- Secure fallback logging when SMTP credentials are not configured in .env.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

log = logging.getLogger("leadsweep.email")

OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "")


def _get_email_cfg() -> dict[str, Any]:
    """Retrieve email configuration from settings or environment dynamically."""
    from leadsweep.config import get_settings
    try:
        s = get_settings()
        owner = getattr(s, "owner_email", None) or os.environ.get("OWNER_EMAIL", "")
        from_email = getattr(s, "from_email", None) or os.environ.get("FROM_EMAIL", "")
        from_name = getattr(s, "from_name", None) or os.environ.get("FROM_NAME", "LeadSweep")
        smtp_host = getattr(s, "smtp_host", None) or os.environ.get("SMTP_HOST", "")
        smtp_port = getattr(s, "smtp_port", None) or int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = getattr(s, "smtp_username", None) or os.environ.get("SMTP_USERNAME", "")
        smtp_pass = getattr(s, "smtp_password", None) or os.environ.get("SMTP_PASSWORD", "")
        smtp_tls = getattr(s, "smtp_use_tls", True)
        return {
            "owner": owner,
            "from_email": from_email,
            "from_name": from_name,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "smtp_user": smtp_user,
            "smtp_pass": smtp_pass,
            "smtp_tls": smtp_tls,
        }
    except Exception:
        return {
            "owner": os.environ.get("OWNER_EMAIL", ""),
            "from_email": os.environ.get("FROM_EMAIL", ""),
            "from_name": os.environ.get("FROM_NAME", "LeadSweep"),
            "smtp_host": os.environ.get("SMTP_HOST", ""),
            "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
            "smtp_user": os.environ.get("SMTP_USERNAME", ""),
            "smtp_pass": os.environ.get("SMTP_PASSWORD", ""),
            "smtp_tls": True,
        }


class EmailService:
    """Provider-neutral SMTP email delivery service."""

    @classmethod
    def _send(cls, to_address: str, subject: str, html_body: str, text_body: str) -> bool:
        cfg = _get_email_cfg()
        smtp_host = cfg["smtp_host"]
        smtp_user = cfg["smtp_user"]
        smtp_pass = cfg["smtp_pass"]
        smtp_port = cfg["smtp_port"]
        from_email = cfg["from_email"]
        from_name = cfg["from_name"]
        formatted_from = f"{from_name} <{from_email}>"

        if not smtp_host or not smtp_user:
            log.info(
                "[EMAIL NOTIFICATION DISPATCHED] To: %s | From: %s | Subject: %s\nText Content:\n%s",
                to_address, formatted_from, subject, text_body
            )
            return True

        # Build message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formatted_from
        msg["To"] = to_address

        part1 = MIMEText(text_body, "plain", "utf-8")
        part2 = MIMEText(html_body, "html", "utf-8")
        msg.attach(part1)
        msg.attach(part2)

        # Retry logic for transient SMTP network/socket errors (up to 3 attempts with backoff)
        import time
        max_attempts = 3
        backoff_delays = [1.0, 2.5]

        for attempt in range(1, max_attempts + 1):
            try:
                if smtp_port == 465:
                    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=12.0) as server:
                        if smtp_pass:
                            server.login(smtp_user, smtp_pass)
                        server.sendmail(from_email, [to_address], msg.as_string())
                else:
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=12.0) as server:
                        if cfg["smtp_tls"]:
                            server.starttls()
                        if smtp_pass:
                            server.login(smtp_user, smtp_pass)
                        server.sendmail(from_email, [to_address], msg.as_string())
                log.info("Successfully delivered email to %s (Subject: %s, Attempt: %d)", to_address, subject, attempt)
                return True
            except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as auth_err:
                # Permanent failure: do not retry
                log.error("Permanent SMTP failure delivering email to %s: %s (will not retry)", to_address, auth_err)
                return False
            except Exception as err:
                if attempt < max_attempts:
                    delay = backoff_delays[attempt - 1]
                    log.warning("Transient SMTP failure (attempt %d/%d) to %s: %s. Retrying in %.1fs...", attempt, max_attempts, to_address, err, delay)
                    time.sleep(delay)
                else:
                    log.error("Failed to deliver SMTP email to %s after %d attempts via %s:%s: %s", to_address, max_attempts, smtp_host, smtp_port, err)
                    return False
        return False

    @classmethod
    def notify_owner_password_reset_requested(cls, user_email: str, user_name: str, reset_url: str) -> bool:
        """Notify admin/owner when a user requests a password reset."""
        cfg = _get_email_cfg()
        owner_email = cfg["owner"]
        subject = f"[Security Alert] Password Reset Request: {user_email}"
        text_body = f"""
Security Notice: Password Reset Requested

A user has requested to reset their password on LeadSweep:
- User Email: {user_email}
- User Name: {user_name}
- Reset Link: {reset_url}

If this request is legitimate, the user has also been sent their reset instructions.
As administrator, you can review this user's account in your Admin Dashboard.
"""
        html_body = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 26px; border: 1px solid #1e293b; background: #0c1222; color: #f8fafc; border-radius: 14px;">
  <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; border-bottom: 1px solid #1e293b; padding-bottom: 12px;">
    <h2 style="color: #f59e0b; margin: 0; font-size: 19px;">Password Reset Request</h2>
    <span style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700;">SECURITY NOTIFICATION</span>
  </div>
  <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; line-height: 1.8;">
    <tr><td style="color: #94a3b8; width: 130px;"><strong>User Name:</strong></td><td>{user_name}</td></tr>
    <tr><td style="color: #94a3b8;"><strong>Email Address:</strong></td><td><a href="mailto:{user_email}" style="color: #38bdf8; text-decoration: none;">{user_email}</a></td></tr>
  </table>
  <div style="background: #131d35; border: 1px solid #1e293b; border-radius: 10px; padding: 18px; margin: 20px 0;">
    <p style="margin: 0; color: #cbd5e1; font-size: 13px; line-height: 1.6;">
      The user has been issued an email with a secure password reset link. This alert is sent to you as the platform owner to maintain full security oversight.
    </p>
  </div>
</div>
"""
        return cls._send(owner_email, subject, html_body, text_body)

    @classmethod
    def notify_user_password_reset_link(cls, user_email: str, user_name: str, reset_url: str) -> bool:
        """Send secure password reset link to the user."""
        cfg = _get_email_cfg()
        sender_email = cfg["from_email"]
        subject = "Reset Your LeadSweep Password"
        text_body = f"""
Dear {user_name},

We received a request to reset your password for your LeadSweep account ({user_email}).

To set a new password, click the link below or copy and paste it into your browser:
{reset_url}

This link is valid for 24 hours. If you did not request a password reset, you can safely ignore this email; your current password will remain unchanged.

Best regards,
The LeadSweep admin
{sender_email}
"""
        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin: 0; padding: 0; background-color: #050811; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <div style="max-width: 600px; margin: 30px auto; background: #0c1222; border: 1px solid #1e293b; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
    <div style="background: linear-gradient(135deg, #10b981, #06b6d4); padding: 28px 32px; text-align: left;">
      <h2 style="color: #ffffff; margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -0.02em;">Password Reset Request</h2>
      <p style="color: rgba(255,255,255,0.9); margin: 6px 0 0 0; font-size: 13px;">LeadSweep Account Security</p>
    </div>
    <div style="padding: 32px; color: #f1f5f9; font-size: 14px; line-height: 1.7;">
      <p style="margin-top: 0;">Dear <strong>{user_name}</strong>,</p>
      <p>We received a request to reset the password for your account associated with <strong>{user_email}</strong>.</p>
      <p>Click the button below to choose a new password:</p>

      <div style="text-align: center; margin: 30px 0;">
        <a href="{reset_url}" style="background: linear-gradient(135deg, #10b981, #06b6d4); color: #ffffff; padding: 13px 32px; border-radius: 10px; text-decoration: none; font-weight: 700; font-size: 14px; display: inline-block; box-shadow: 0 4px 14px rgba(16, 185, 129, 0.4);">
          Reset My Password →
        </a>
      </div>

      <p style="color: #94a3b8; font-size: 13px; line-height: 1.6;">
        If you didn't request a password reset, you can safely disregard this email. Your password will not change until you access the link above and create a new one.
      </p>

      <hr style="border: 0; border-top: 1px solid #1e293b; margin: 24px 0 20px 0;" />
      <p style="margin-bottom: 0; color: #cbd5e1; font-size: 13px;">
        Warm regards,<br />
        <strong>LeadSweep</strong><br />
        <span style="color: #64748b; font-size: 12px;">Self-hosted lead discovery</span><br />
        <a href="mailto:{sender_email}" style="color: #38bdf8; font-size: 12px; text-decoration: none;">{sender_email}</a>
      </p>
    </div>
  </div>
</body>
</html>
"""
        return cls._send(user_email, subject, html_body, text_body)
