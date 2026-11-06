"""
Forms for the temporary Django-template UI.

v1 rules:
- Priority is auto-derived from expected_completion (not user-editable).
- Reminder timing is algorithm-driven from priority (no preset picker).
- Effort is user-chosen for Focus mode.
"""

from datetime import timedelta

from django import forms
from django.utils import timezone
from .models import Task


class TaskForm(forms.ModelForm):
    """Create / edit a task. Priority & reminder are computed on save."""

    expected_completion = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'},
            format='%Y-%m-%dT%H:%M',
        ),
        input_formats=['%Y-%m-%dT%H:%M'],
        help_text='When you intend to finish. Priority and reminder follow from this.',
    )

    class Meta:
        model = Task
        fields = [
            'title',
            'description',
            'expected_completion',
            'effort',
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
            'effort': forms.Select(attrs={'class': 'form-select'}),
            'recurrence': forms.Select(attrs={'class': 'form-select'}),
            'recurrence_weekdays': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 0,2,4  (Mon,Wed,Fri) — optional',
            }),
        }
        labels = {
            'expected_completion': 'Expected completion',
            'effort': 'Effort',
            'recurrence_weekdays': 'Weekdays (for weekly rules)',
        }
        help_texts = {
            'effort': 'How much capacity this needs — used in Focus mode.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
    """Focus mode filters: effort + priority + status."""

    effort = forms.ChoiceField(
        choices=[('', 'Any effort')] + list(Task.Effort.choices),
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
