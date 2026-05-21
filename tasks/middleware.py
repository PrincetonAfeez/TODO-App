from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


class SessionKeyMiddleware:
    """Guarantee every visitor has a stable session key for scoping data."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, "session") and not request.session.session_key:
            request.session.create()
        return self.get_response(request)


class VisitorTimezoneMiddleware:
    """Activate the visitor timezone from the browser cookie when present."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tz_name = request.COOKIES.get("timezone")
        if tz_name:
            try:
                timezone.activate(ZoneInfo(tz_name))
            except ZoneInfoNotFoundError:
                pass
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
