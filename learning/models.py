import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


class Course(models.Model):
    """A teacher-authored course available to staff in the LMS."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    summary = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_courses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["title"]
        permissions = [
            ("publish_course", "Can publish or archive courses"),
            ("view_all_courses", "Can view all courses regardless of author"),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)[:200] or "course"
            slug = base_slug
            suffix = 2
            while Course.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug[:210 - len(str(suffix))]}-{suffix}"
                suffix += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class CourseModule(models.Model):
    """Ordered section/module within a course."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=1)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "position"], name="unique_module_position_per_course"
            ),
            models.CheckConstraint(condition=Q(position__gte=1), name="module_position_gte_1"),
        ]
        indexes = [models.Index(fields=["course", "is_published", "position"])]

    def __str__(self):
        return f"{self.course}: {self.title}"


class LearningActivity(models.Model):
    """Typed lesson resource; no learner attempts or enrollment are modeled."""

    class ActivityType(models.TextChoices):
        TEXT = "text", "Text lesson"
        VIDEO = "video", "Video"
        LINK = "link", "External link"
        FILE = "file", "File/resource link"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(
        CourseModule, on_delete=models.CASCADE, related_name="activities"
    )
    title = models.CharField(max_length=200)
    activity_type = models.CharField(max_length=10, choices=ActivityType.choices)
    position = models.PositiveIntegerField(default=1)
    body = models.TextField(blank=True, help_text="Lesson text or instructions.")
    resource_url = models.URLField(blank=True, help_text="Video, file, or external URL.")
    estimated_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["module", "position"], name="unique_activity_position_per_module"
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="activity_position_gte_1"
            ),
        ]
        indexes = [models.Index(fields=["module", "is_published", "position"])]

    def clean(self):
        super().clean()
        if self.activity_type == self.ActivityType.TEXT and not self.body.strip():
            raise ValidationError({"body": "Text lessons need lesson content."})
        if self.activity_type != self.ActivityType.TEXT and not self.resource_url:
            raise ValidationError({"resource_url": "This activity type needs a resource URL."})

    def __str__(self):
        return f"{self.module}: {self.title}"



