"""Send transactional email via Brevo (Sendinblue) API."""
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

logger = logging.getLogger(__name__)

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'
DEFAULT_HR_SENDER_EMAIL = 'hr@nexgenfuelworks.com'
LEGACY_SENDER_EMAIL = 'info@nexgenfuelworks.com'


def normalize_hr_sender_email(value: str | None) -> str:
    """Use hr@ for all outbound mail; migrate away from legacy info@."""
    email = (value or '').strip().lower()
    if not email or email == LEGACY_SENDER_EMAIL:
        return DEFAULT_HR_SENDER_EMAIL
    return email


def brevo_configured() -> bool:
    return bool((current_app.config.get('BREVO_API_KEY') or '').strip())


def send_transactional_email(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    text_content: str | None = None,
) -> bool:
    """
    Send one email through Brevo. Returns True on success, False on failure or missing config.
    """
    api_key = (current_app.config.get('BREVO_API_KEY') or '').strip()
    sender_email = normalize_hr_sender_email(current_app.config.get('BREVO_SENDER_EMAIL'))
    sender_name = (current_app.config.get('BREVO_SENDER_NAME') or 'HR NexGen Fuelworks').strip() or 'HR NexGen Fuelworks'

    if not api_key or not sender_email:
        logger.warning('Brevo not configured (BREVO_API_KEY / BREVO_SENDER_EMAIL); email not sent to %s', to_email)
        return False

    payload = {
        'sender': {'name': sender_name, 'email': sender_email},
        'to': [{'email': to_email}],
        'subject': subject,
        'htmlContent': html_content,
    }
    if text_content:
        payload['textContent'] = text_content

    req = Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'accept': 'application/json',
            'api-key': api_key,
            'content-type': 'application/json',
        },
        method='POST',
    )
    try:
        with urlopen(req, timeout=30) as resp:
            if 200 <= resp.status < 300:
                return True
            logger.error('Brevo API unexpected status %s for %s', resp.status, to_email)
            return False
    except HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode('utf-8', errors='replace')[:500]
        except Exception:
            pass
        logger.error('Brevo API HTTP error %s for %s: %s', exc.code, to_email, body)
        return False
    except URLError as exc:
        logger.error('Brevo API connection error for %s: %s', to_email, exc)
        return False
