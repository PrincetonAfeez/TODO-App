""" Forms for the project """

from django import forms

from .models import (
    RecurrenceFrequency,
    Task,
    TaskList,
)

WEEKDAY_CHOICES = [
    (1, "Mon"),
    (2, "Tue"),
    (4, "Wed"),
    (8, "Thu"),
    (16, "Fri"),
    (32, "Sat"),
    (64, "Sun"),
]


class TaskListForm(forms.ModelForm):
    class Meta:
        model = TaskList
        fields = ["name"]

    def clean_name(self):
        return self.cleaned_data["name"].strip()


class TaskForm(forms.ModelForm):
    due_date = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
    )

    class Meta:
        model = Task
        fields = ["title", "notes", "due_date", "priority"]
        widgets = {
            "title": forms.TextInput(attrs={"autocomplete": "off"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_title(self):
        return self.cleaned_data["title"].strip()


class RecurrenceForm(forms.Form):
    frequency = forms.ChoiceField(choices=RecurrenceFrequency.choices)
    interval = forms.IntegerField(min_value=1, max_value=52, initial=1)
    weekdays = forms.MultipleChoiceField(
        choices=[(str(value), label) for value, label in WEEKDAY_CHOICES],
        required=False,
    )
    day_of_month = forms.IntegerField(min_value=1, max_value=31, required=False)
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned = super().clean()
        frequency = cleaned.get("frequency")
        if frequency == RecurrenceFrequency.WEEKLY and not cleaned.get("weekdays"):
            raise forms.ValidationError("Choose at least one weekday.")
        if frequency == RecurrenceFrequency.MONTHLY and not cleaned.get("day_of_month"):
            raise forms.ValidationError("Choose a day of the month.")
        return cleaned

    @property
    def weekday_mask(self) -> int | None:
        values = self.cleaned_data.get("weekdays") or []
        if not values:
            return None
        return sum(int(value) for value in values)
