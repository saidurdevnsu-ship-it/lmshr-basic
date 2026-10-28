from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Designation(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Employee(models.Model):
    """HR profile for a login account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="employee")
    employee_id = models.CharField("employee ID", max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="employees")
    designation = models.ForeignKey(Designation, on_delete=models.PROTECT, related_name="employees")
    joining_date = models.DateField()
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account = models.CharField("bank account no.", max_length=50, blank=True)
    is_active = models.BooleanField(default=True, help_text="Inactive employees are skipped in attendance.")

    class Meta:
        ordering = ["employee_id"]
        permissions = [("manage_hr", "Can manage HR records for all employees")]

    def __str__(self):
        return f"{self.full_name} ({self.employee_id})"

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.get_username()


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.name} ({self.date:%d %b %Y})"


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        HALF_DAY = "half_day", "Half day"
        ABSENT = "absent", "Absent"
        ON_LEAVE = "on_leave", "On leave"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField(db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PRESENT)
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-date", "employee"]
        verbose_name_plural = "attendance"
        constraints = [models.UniqueConstraint(fields=["employee", "date"], name="one_attendance_per_day")]

    def __str__(self):
        return f"{self.employee.full_name} · {self.date:%d %b %Y} · {self.get_status_display()}"


class LeaveType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    days_per_year = models.PositiveSmallIntegerField(
        default=0, help_text="Yearly allowance. 0 means no limit (e.g. unpaid leave)."
    )
    is_paid = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ReviewStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class LeaveRequest(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.DecimalField(max_digits=5, decimal_places=1, default=0, editable=False,
                               help_text="Working days, excluding weekends and holidays.")
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=ReviewStatus.choices, default=ReviewStatus.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    editable=False, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    review_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=models.F("start_date")), name="leave_end_after_start"),
        ]

    def __str__(self):
        return f"{self.employee.full_name} · {self.leave_type} · {self.start_date:%d %b} – {self.end_date:%d %b %Y}"

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The end date can't be before the start date."})
