""" Template tags for the project """

from django import template

register = template.Library()


def _weekday_selected(form, recurrence, bit):
    try:
        bit_value = str(int(bit))
    except (TypeError, ValueError):
        return False
    if form and form.is_bound:
        data = form.data
        if hasattr(data, "getlist"):
            submitted = data.getlist("weekdays")
        else:
            raw = data.get("weekdays", [])
            submitted = raw if isinstance(raw, list) else [raw] if raw else []
        return bit_value in submitted
    if recurrence and recurrence.weekday_mask:
        try:
            return bool(recurrence.weekday_mask & int(bit_value))
        except (TypeError, ValueError):
            return False
    return False


@register.simple_tag
def weekday_selected(form, recurrence, bit):
    return _weekday_selected(form, recurrence, bit)
