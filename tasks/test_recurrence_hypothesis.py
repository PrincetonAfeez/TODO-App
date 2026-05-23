"""Property-based tests for recurrence date math in tasks/services.py."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta

import pytest
from django.utils import timezone
from hypothesis import given, settings
from hypothesis import strategies as st

from tasks import services
from tasks.models import Recurrence, RecurrenceFrequency

pytestmark = pytest.mark.django_db


@settings(max_examples=100, deadline=None)
@given(
    days=st.integers(min_value=1, max_value=400),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
)
def test_add_local_days_preserves_wall_clock(days, hour, minute):
    local_base = timezone.localtime(
        timezone.make_aware(datetime(2024, 1, 15, hour, minute))
    )

    result = services._add_local_days(local_base, days)

    assert result.date() == local_base.date() + timedelta(days=days)
    assert result.hour == hour
    assert result.minute == minute
    assert result.second == local_base.second


@settings(max_examples=100, deadline=None)
@given(interval=st.integers(min_value=1, max_value=52))
def test_daily_compute_next_due_date_advances_by_interval(interval):
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.DAILY,
        interval=interval,
    )
    base = timezone.localtime(timezone.make_aware(datetime(2024, 6, 15, 14, 30)))

    next_due = services.compute_next_due_date(base, recurrence)

    assert next_due is not None
    assert (next_due.date() - base.date()).days == interval
    assert next_due.hour == base.hour
    assert next_due.minute == base.minute


@settings(max_examples=100, deadline=None)
@given(extra_days=st.integers(min_value=0, max_value=60))
def test_compute_next_due_date_respects_end_date(extra_days):
    base_date = date(2024, 6, 1)
    end_date = base_date + timedelta(days=extra_days)
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.DAILY,
        interval=1,
        end_date=end_date,
    )
    base = timezone.localtime(
        timezone.make_aware(datetime.combine(base_date, time(9, 0)))
    )

    next_due = services.compute_next_due_date(base, recurrence)

    if extra_days == 0:
        assert next_due is None
    else:
        assert next_due is not None
        assert next_due.date() <= end_date


@settings(max_examples=100, deadline=None)
@given(
    year=st.integers(min_value=2020, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    interval=st.integers(min_value=1, max_value=12),
    dom=st.integers(min_value=1, max_value=31),
)
def test_monthly_compute_next_due_date_clamps_day_of_month(
    year, month, day, interval, dom
):
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.MONTHLY,
        interval=interval,
        day_of_month=dom,
    )
    base = timezone.localtime(timezone.make_aware(datetime(year, month, day, 10, 0)))

    next_due = services.compute_next_due_date(base, recurrence)

    assert next_due is not None
    last_day = calendar.monthrange(next_due.year, next_due.month)[1]
    assert 1 <= next_due.day <= last_day
    assert next_due.day == min(dom, last_day)


@settings(max_examples=50, deadline=None)
@given(
    weekday_mask=st.integers(min_value=1, max_value=127),
    interval=st.integers(min_value=1, max_value=8),
)
def test_weekly_masked_next_due_date_matches_mask(weekday_mask, interval):
    recurrence = Recurrence(
        frequency=RecurrenceFrequency.WEEKLY,
        interval=interval,
        weekday_mask=weekday_mask,
    )
    base = timezone.localtime(timezone.make_aware(datetime(2024, 6, 10, 9, 0)))

    next_due = services._next_weekly(base, recurrence)

    assert next_due.date() > base.date()
    bit = 1 << next_due.weekday()
    assert recurrence.weekday_mask & bit
