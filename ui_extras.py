from django import template

register = template.Library()

BADGES = {
    "published": "success", "confirmed": "success", "paid": "success", "valid": "success",
    "pending": "warning", "draft": "secondary", "failed": "danger", "rejected": "danger",
    "cancelled": "danger", "refunded": "info", "used": "dark",
}


@register.filter
def badge(value):
    return BADGES.get(str(value), "secondary")


@register.filter
def mod(value, arg):
    try:
        return int(value) % int(arg)
    except (TypeError, ValueError):
        return 0


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Keep the current querystring but override some keys (used by pagination)."""
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        query[key] = value
    return query.urlencode()


@register.filter
def get_item(mapping, key):
    return mapping.get(key)
