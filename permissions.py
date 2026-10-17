from accounts.permissions import ADMIN, ORGANIZER, get_role


def can_manage_event(user, event):
    """Admins manage everything, organizers only their own events."""
    role = get_role(user)
    if role == ADMIN:
        return True
    return role == ORGANIZER and event.organizer_id == user.id
