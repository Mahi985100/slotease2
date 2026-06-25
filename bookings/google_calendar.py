"""
Google Calendar integration helpers for SlotEase.

Uses the Google Calendar API v3 via simple HTTP requests (no extra SDK needed).
Requires GOOGLE_CALENDAR_CREDENTIALS_JSON set in environment with a service
account JSON, plus each tenant owner's calendar ID in GOOGLE_CALENDAR_ID
(or per-tenant storage).

For simplicity this module builds a minimal OAuth2 token from a service-account
key file and makes direct REST calls so there's no extra google-auth dependency
required at runtime — just add the JSON key and configure the env vars.

If you want full OAuth2 "connect your Google account" flow, replace the
_get_access_token() below with the standard google-auth library approach.
"""
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

from django.conf import settings


def _get_access_token():
    """
    Return a short-lived OAuth2 access token from a service-account key.
    Reads GOOGLE_SERVICE_ACCOUNT_JSON from settings (path to the JSON key file
    or the JSON string itself).
    Returns None if not configured so callers can degrade gracefully.
    """
    import base64
    import hashlib
    import hmac

    key_source = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", None)
    if not key_source:
        return None

    try:
        if key_source.strip().startswith("{"):
            key_data = json.loads(key_source)
        else:
            with open(key_source) as f:
                key_data = json.load(f)

        # Build a JWT assertion
        import jwt  # PyJWT — add to requirements if using this feature
        now = int(time.time())
        payload = {
            "iss": key_data["client_email"],
            "scope": "https://www.googleapis.com/auth/calendar",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600,
        }
        private_key = key_data["private_key"]
        assertion = jwt.encode(payload, private_key, algorithm="RS256")

        data = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_data = json.loads(resp.read())
        return token_data.get("access_token")
    except Exception:
        return None


def _calendar_id(tenant):
    """Return the Google Calendar ID for this tenant, or 'primary'."""
    return getattr(tenant, "google_calendar_id", None) or getattr(
        settings, "GOOGLE_CALENDAR_ID", "primary"
    )


def create_calendar_event(appt):
    """
    Create a Google Calendar event for `appt` (an Appointment instance).
    Saves the returned event ID to appt.google_calendar_event_id.
    Returns the event ID string or None on failure.
    """
    token = _get_access_token()
    if not token:
        return None

    cal_id = urllib.parse.quote(_calendar_id(appt.tenant), safe="")
    start_dt = datetime.combine(appt.date, appt.start_time).isoformat()
    end_dt = datetime.combine(appt.date, appt.end_time).isoformat()

    event = {
        "summary": f"{appt.service.name} — {appt.customer_name}",
        "description": (
            f"Customer: {appt.customer_name}\n"
            f"Phone: {appt.customer_phone}\n"
            f"Email: {appt.customer_email}\n"
            f"Staff: {appt.staff.name}\n"
            f"Notes: {appt.notes}"
        ),
        "start": {"dateTime": start_dt, "timeZone": "UTC"},
        "end": {"dateTime": end_dt, "timeZone": "UTC"},
        "reminders": {"useDefault": False, "overrides": [
            {"method": "email", "minutes": 1440},  # 24 h
            {"method": "popup", "minutes": 60},    # 1 h
        ]},
    }

    url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events"
    body = json.dumps(event).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        event_id = result.get("id", "")
        if event_id:
            appt.google_calendar_event_id = event_id
            appt.save(update_fields=["google_calendar_event_id"])
        return event_id
    except Exception:
        return None


def delete_calendar_event(appt):
    """Delete the Google Calendar event linked to `appt`, if any."""
    if not appt.google_calendar_event_id:
        return
    token = _get_access_token()
    if not token:
        return
    cal_id = urllib.parse.quote(_calendar_id(appt.tenant), safe="")
    event_id = urllib.parse.quote(appt.google_calendar_event_id, safe="")
    url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events/{event_id}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="DELETE"
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass
