from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Grade(models.Model):
    name = models.CharField(max_length=50, unique=True, help_text='e.g. "Class 8" or "Grade 10".')
    order = models.PositiveSmallIntegerField(default=0, help_text="Lower numbers are listed first.")

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class KnowledgeSource(models.Model):
    """A textbook or notes file that Claude reads when generating questions for a subject and grade."""

    MAX_UPLOAD_MB = 20

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="sources")
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, related_name="sources")
    title = models.CharField(max_length=200)
    file = models.FileField(
        upload_to="knowledge/%Y/%m/",
        validators=[FileExtensionValidator(["pdf", "txt", "md"])],
        help_text=f"PDF, TXT or Markdown, up to {MAX_UPLOAD_MB} MB. Split very large books into chapters.",
    )
    is_active = models.BooleanField(
        default=True, help_text="Only active sources are used when generating questions."
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["subject", "grade", "title"]
        verbose_name = "book / knowledge source"
        verbose_name_plural = "books & knowledge sources"

    def __str__(self):
        return f"{self.title} ({self.subject}, {self.grade})"

    @property
    def is_pdf(self):
        return self.file.name.lower().endswith(".pdf")


class Question(models.Model):
    class QuestionType(models.TextChoices):
        MCQ = "mcq", "Multiple choice"
        SHORT = "short", "Short answer"
        LONG = "long", "Long answer / creative"
        TRUE_FALSE = "true_false", "True / false"
        FILL_BLANK = "fill_blank", "Fill in the blank"

    class Difficulty(models.TextChoices):
        EASY = "easy", "Easy"
        MEDIUM = "medium", "Medium"
        HARD = "hard", "Hard"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft (needs review)"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="questions")
    grade = models.ForeignKey(Grade, on_delete=models.PROTECT, related_name="questions")
    topic = models.CharField(max_length=200, blank=True)
    question_type = models.CharField(max_length=12, choices=QuestionType.choices)
    difficulty = models.CharField(max_length=8, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    text = models.TextField("question")
    options = models.JSONField(
        default=list, blank=True, help_text='Multiple-choice options as a JSON list, e.g. ["A", "B", "C", "D"].'
    )
    answer = models.TextField()
    explanation = models.TextField(blank=True)
    source_reference = models.CharField(
        max_length=255, blank=True, help_text="Chapter / page in the book the question is based on."
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    ai_generated = models.BooleanField(default=False, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["subject", "grade", "status"])]

    def __str__(self):
        return self.text if len(self.text) <= 80 else f"{self.text[:77]}..."
