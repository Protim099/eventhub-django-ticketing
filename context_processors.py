from accounts.permissions import get_role

from .models import PlatformSettings


def site_context(request):
    return {"site": PlatformSettings.load(), "user_role": get_role(request.user)}
