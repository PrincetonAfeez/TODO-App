"""Tests for recurrence template helpers in ``task_extras``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tasks.forms import RecurrenceForm
from tasks.models import Recurrence, RecurrenceFrequency
from tasks.templatetags.task_extras import _weekday_selected, weekday_selected


@pytest.mark.parametrize("bit", ["not-a-bit", None, [], {}])
def test_weekday_selected_invalid_bit_returns_false(bit):
    assert _weekday_selected(None, None, bit) is False


@pytest.mark.django_db
def test_weekday_selected_uses_recurrence_mask_when_form_unbound():
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=1,
        weekday_mask=5,
    )

    assert _weekday_selected(None, recurrence, 1) is True
    assert _weekday_selected(None, recurrence, 4) is True
    assert _weekday_selected(None, recurrence, 2) is False


@pytest.mark.django_db
def test_weekday_selected_returns_false_without_form_or_recurrence():
    assert _weekday_selected(None, None, 1) is False


@pytest.mark.django_db
def test_weekday_selected_prefers_bound_form_data():
    form = RecurrenceForm(
        {
            "frequency": "weekly",
            "interval": "2",
            "weekdays": ["4", "16"],
        }
    )
    assert _weekday_selected(form, None, 4) is True
    assert _weekday_selected(form, None, 1) is False


def test_weekday_selected_bound_form_dict_without_getlist():
    form = SimpleNamespace(is_bound=True, data={"weekdays": "4"})
    assert _weekday_selected(form, None, 4) is True
    assert _weekday_selected(form, None, 1) is False

    list_form = SimpleNamespace(is_bound=True, data={"weekdays": ["1", "4"]})
    assert _weekday_selected(list_form, None, 4) is True
    assert _weekday_selected(list_form, None, 16) is False


def test_weekday_selected_recurrence_mask_bitwise_failure_returns_false():
    class WeirdMask:
        def __bool__(self) -> bool:
            return True

        def __and__(self, other):
            raise TypeError("unsupported mask")

    recurrence = SimpleNamespace(weekday_mask=WeirdMask())
    assert _weekday_selected(None, recurrence, 1) is False


def test_weekday_selected_tag_matches_helper():
    recurrence = SimpleNamespace(weekday_mask=4)
    assert weekday_selected(None, recurrence, 4) is True
    assert weekday_selected(None, recurrence, 1) is False
