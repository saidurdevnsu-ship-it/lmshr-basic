from django import forms
from django.utils import timezone

from .models import Attendance, Employee, LeaveRequest
from .services import validate_leave

DATE_INPUT = forms.DateInput(attrs={"type": "date"})


class LeaveRequestForm(forms.ModelForm):
    """Used by both employees (for themselves) and HR managers (for anyone)."""

    # Set by the admin before validation when the requester is applying for themselves.
    own_employee = None

    class Meta:
        model = LeaveRequest
        fields = ["employee", "leave_type", "start_date", "end_date", "reason", "review_note"]
        widgets = {"start_date": DATE_INPUT, "end_date": DATE_INPUT, "reason": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned = super().clean()
        employee = cleaned.get("employee") or self.own_employee
        start, end, leave_type = cleaned.get("start_date"), cleaned.get("end_date"), cleaned.get("leave_type")
        if employee and start and end and leave_type and end >= start:
            draft = LeaveRequest(pk=self.instance.pk, employee=employee, leave_type=leave_type,
                                 start_date=start, end_date=end)
            for problem in validate_leave(draft):
                self.add_error(None, problem)
        return cleaned


class GeneratePayslipsForm(forms.Form):
    month = forms.TypedChoiceField(coerce=int, choices=[(m, timezone.datetime(2000, m, 1).strftime("%B")) for m in range(1, 13)])
    year = forms.IntegerField(min_value=2000, max_value=2100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        # Default to the previous month: payroll is usually run after a month closes.
        prev = (today.replace(day=1) - timezone.timedelta(days=1))
        self.fields["month"].initial = prev.month
        self.fields["year"].initial = prev.year


class MarkAttendanceDateForm(forms.Form):
    date = forms.DateField(widget=DATE_INPUT)


def attendance_status_choices():
    return Attendance.Status.choices


def active_employees():
    return Employee.objects.filter(is_active=True).select_related("user", "department", "designation")
