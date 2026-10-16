"""Role helpers and decorators used across the project."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

ADMIN, ORGANIZER, CUSTOMER = "admin", "organizer", "customer"


def get_role(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return ADMIN
    profile = getattr(user, "profile", None)
    return profile.role if profile else CUSTOMER


def role_required(*roles):
    """Require login AND one of the given roles, otherwise raise 403."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if get_role(request.user) not in roles:
                raise PermissionDenied("You do not have permission to access this page.")
            return view(request, *args, **kwargs)

        return login_required(wrapped)

    return decorator
