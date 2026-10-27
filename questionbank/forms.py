from django import forms

from .ai import LANGUAGES
from .models import Grade, KnowledgeSource, Question, Subject


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
    question_type = forms.ChoiceField(choices=Question.QuestionType.choices, initial=Question.QuestionType.MCQ)
    difficulty = forms.ChoiceField(choices=Question.Difficulty.choices, initial=Question.Difficulty.MEDIUM)
    count = forms.IntegerField(label="Number of questions", min_value=1, max_value=30, initial=10)
    language = forms.ChoiceField(choices=LANGUAGES.items(), initial="en")

    def clean(self):
        cleaned = super().clean()
        subject, grade = cleaned.get("subject"), cleaned.get("grade")
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
        fields = ["subject", "grade", "title", "file", "is_active"]

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f and f.size > KnowledgeSource.MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(
                f"This file is larger than {KnowledgeSource.MAX_UPLOAD_MB} MB. Upload it chapter by chapter instead."
            )
        return f
