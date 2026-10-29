from django import forms

from .ai import LANGUAGES
from .documents import UnreadableDocument, extract_text
from .models import Grade, KnowledgeSource, Question, QuestionBlueprint, Subject


class MaterialCheckboxes(forms.CheckboxSelectMultiple):
    """Ticks for materials, each tagged with its subject and grade so the page shows only the matching ones."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            option["attrs"]["data-pair"] = f"{value.instance.subject_id}:{value.instance.grade_id}"
        return option


class MaterialChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.label


def check_materials(materials, subject, grade):
    """Selected materials must belong to the chosen subject and grade."""
    wrong = [m for m in materials if (m.subject_id, m.grade_id) != (subject.pk, grade.pk)]
    if wrong:
        raise forms.ValidationError(f"“{wrong[0].title}” isn't for {subject} / {grade}. Untick it or change the "
                                    "subject and grade.")


class GenerateQuestionsForm(forms.Form):
    subject = forms.ModelChoiceField(queryset=Subject.objects.all(), empty_label="Select a subject")
    grade = forms.ModelChoiceField(queryset=Grade.objects.all(), empty_label="Select a grade")
    topic = forms.CharField(
        required=False,
        max_length=200,
        label="Topic or chapter",
        help_text="Optional. Leave blank to use the whole book.",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Chapter 3: Photosynthesis"}),
    )
    sources = MaterialChoiceField(
        queryset=KnowledgeSource.objects.filter(is_active=True).select_related("subject", "grade"),
        required=False, widget=MaterialCheckboxes, label="Materials to use",
        help_text="Tick the chapters or files to use. Leave all unticked to use every active material.",
    )
    question_type = forms.ChoiceField(choices=Question.QuestionType.choices, initial=Question.QuestionType.MCQ)
    difficulty = forms.ChoiceField(choices=Question.Difficulty.choices, initial=Question.Difficulty.MEDIUM)
    count = forms.IntegerField(label="How many", min_value=1, max_value=30, initial=10)
    language = forms.ChoiceField(choices=LANGUAGES.items(), initial="en")

    def clean(self):
        cleaned = super().clean()
        subject, grade = cleaned.get("subject"), cleaned.get("grade")
        if subject and grade and cleaned.get("sources"):
            check_materials(cleaned["sources"], subject, grade)
        if subject and grade and not KnowledgeSource.objects.filter(
            subject=subject, grade=grade, is_active=True
        ).exists():
            raise forms.ValidationError(
                f"No book is uploaded for {subject} / {grade} yet. Upload one under "
                "“Books & knowledge sources”, then come back."
            )
        return cleaned


class KnowledgeSourceForm(forms.ModelForm):
    class Meta:
        model = KnowledgeSource
        fields = ["subject", "grade", "material_type", "title", "chapter", "topic", "file", "is_active"]

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f and f.size > KnowledgeSource.MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(
                f"This file is larger than {KnowledgeSource.MAX_UPLOAD_MB} MB. Upload it chapter by chapter instead."
            )
        if f and "file" in self.changed_data:
            try:
                self.instance.content_text = extract_text(f)
            except UnreadableDocument as exc:
                raise forms.ValidationError(str(exc))
        return f


class BlueprintForm(forms.ModelForm):
    class Meta:
        model = QuestionBlueprint
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "materials" in self.fields:
            field = self.fields["materials"]
            field.queryset = KnowledgeSource.objects.filter(is_active=True).select_related("subject", "grade")
            field.label_from_instance = lambda m: f"{m.subject} · {m.grade} · {m.label}"

    def clean(self):
        cleaned = super().clean()
        subject = cleaned.get("subject") or getattr(self.instance, "subject", None)
        grade = cleaned.get("grade") or getattr(self.instance, "grade", None)
        materials = cleaned.get("materials")
        if materials and subject and grade:
            try:
                check_materials(materials, subject, grade)
            except forms.ValidationError as exc:
                self.add_error("materials", exc)
        return cleaned
