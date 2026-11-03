"""
Forms for the temporary Django-template UI.
These mirror the Task model fields so we can exercise every backend feature
before the React frontend arrives.
"""

from datetime import timedelta

from django import forms
from django.utils import timezone
from .models import Task


class TaskForm(forms.ModelForm):
    """Create / edit a task. Covers all v1 fields."""

    # Make expected_completion friendlier in the browser
    expected_completion = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M',
        ),
        input_formats=['%Y-%m-%dT%H:%M'],
        help_text='When you intend to finish this task.',
    )

    # Explicit choices so the form stays in sync with settings.REMINDER_PRESETS
    REMINDER_CHOICES = [
        ('', '— no reminder —'),
        ('at_due', 'At due time'),
        ('15_min_before', '15 minutes before'),
        ('1_hour_before', '1 hour before'),
        ('2_hours_before', '2 hours before'),
        ('morning_of', 'Morning of the day'),
        ('1_day_before', '1 day before'),
    ]

    class Meta:
        model = Task
        fields = [
            'title',
            'description',
            'expected_completion',
            'reminder_preset',
            'energy',
            'priority',
            'recurrence',
            'recurrence_weekdays',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'What needs doing?',
                'autofocus': True,
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional notes…',
            }),
            'energy': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'recurrence': forms.Select(attrs={'class': 'form-select'}),
            'recurrence_weekdays': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 0,2,4  (Mon,Wed,Fri) — optional',
            }),
        }
        labels = {
            'expected_completion': 'Expected completion',
            'reminder_preset': 'Reminder',
            'recurrence_weekdays': 'Weekdays (for weekly rules)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reminder_preset'] = forms.ChoiceField(
            choices=self.REMINDER_CHOICES,
            required=False,
            widget=forms.Select(attrs={'class': 'form-select'}),
            label='Reminder',
        )
        # Keep existing value when editing
        if self.instance and self.instance.pk and self.instance.reminder_preset:
            self.fields['reminder_preset'].initial = self.instance.reminder_preset
        # Default expected_completion to now + 1 hour for new tasks
        if not self.instance.pk and not self.data:
            default_dt = timezone.now() + timedelta(hours=1)
            self.fields['expected_completion'].initial = default_dt.strftime('%Y-%m-%dT%H:%M')

    def clean_recurrence_weekdays(self):
        value = self.cleaned_data.get('recurrence_weekdays', '').strip()
        if not value:
            return ''
        parts = [p.strip() for p in value.split(',') if p.strip()]
        for p in parts:
            if not p.isdigit() or not (0 <= int(p) <= 6):
                raise forms.ValidationError(
                    'Use comma-separated numbers 0–6 (0=Mon … 6=Sun).'
                )
        return ','.join(parts)


class FocusFilterForm(forms.Form):
    """Simple filter for Focus mode on the task list."""

    energy = forms.ChoiceField(
        choices=[('', 'Any energy')] + list(Task.Energy.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    priority = forms.ChoiceField(
        choices=[('', 'Any priority')] + list(Task.Priority.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    show = forms.ChoiceField(
        choices=[
            ('open', 'Open only'),
            ('completed', 'Completed only'),
            ('all', 'All'),
            ('overdue', 'Overdue'),
        ],
        required=False,
        initial='open',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
