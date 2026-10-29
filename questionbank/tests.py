import shutil
import tempfile
from datetime import date
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from notifications.models import Notification

from . import ai, workflow
from .models import (
    AcademicEvent, BlueprintItem, FinalPaper, Grade, KnowledgeSource, QuestionBlueprint, Subject,
)
from .reminders import ensure_reminders

MEDIA = tempfile.mkdtemp()


def claude_reply(n):
    return {"questions": [
        {"section": "whatever", "question_type": "short", "text": f"Question {i}?", "options": [], "answer": "A",
         "explanation": "", "marks": 99, "source_reference": "Ch 1"}
        for i in range(n)
    ]}


@override_settings(MEDIA_ROOT=MEDIA)
class BlueprintTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.hod = User.objects.create_user("hod", password="Pw-12345!", is_staff=True)
        self.hod.user_permissions.add(Permission.objects.get(codename="review_blueprint"))
        self.hod = User.objects.get(pk=self.hod.pk)  # reload to clear the permission cache
        self.controller = User.objects.create_superuser("controller", "c@example.com", "Pw-12345!")
        subject, grade = Subject.objects.create(name="Science"), Grade.objects.create(name="Class 8")
        KnowledgeSource.objects.create(subject=subject, grade=grade, title="Book",
                                       file=SimpleUploadedFile("book.txt", b"Plants make food."))
        self.bp = QuestionBlueprint.objects.create(
            title="Science mid-term", subject=subject, grade=grade, assigned_to=self.hod, due_date=date(2026, 12, 1),
            status=QuestionBlueprint.Status.APPROVED,
        )
        BlueprintItem.objects.create(blueprint=self.bp, order=1, section="A", question_type="mcq", count=2, marks_each=1)
        BlueprintItem.objects.create(blueprint=self.bp, order=2, section="B", question_type="short", count=1, marks_each=5)


class FinalPaperTests(BlueprintTestCase):
    def test_marks_sections_and_types_follow_the_blueprint(self):
        with mock.patch.object(ai, "_ask_claude", return_value=claude_reply(3)):
            paper = ai.generate_final_paper(self.bp, self.controller)
        questions = list(paper.questions.all())
        self.assertEqual([q.section for q in questions], ["A", "A", "B"])
        self.assertEqual([q.question_type for q in questions], ["mcq", "mcq", "short"])
        self.assertEqual(paper.total_marks, 7)

    def test_wrong_number_of_questions_is_not_saved(self):
        with mock.patch.object(ai, "_ask_claude", return_value=claude_reply(2)):
            with self.assertRaisesMessage(ai.GenerationError, "wrote 2 questions but the blueprint asks for 3"):
                ai.generate_final_paper(self.bp, self.controller)
        self.assertFalse(FinalPaper.objects.filter(questions__isnull=False).exists())

    def test_generation_runs_in_the_background_and_notifies(self):
        with mock.patch.object(ai.threading, "Thread") as thread:
            paper = ai.start_final_paper(self.bp, self.controller)
        thread.return_value.start.assert_called_once()
        self.assertTrue(paper.is_generating)
        with self.assertRaisesMessage(ai.GenerationError, "already writing"):
            ai.start_final_paper(self.bp, self.controller)

        with mock.patch.object(ai, "_ask_claude", return_value=claude_reply(3)):
            ai.write_final_paper(paper.pk, self.controller.pk)
        paper.refresh_from_db()
        self.assertFalse(paper.is_generating)
        self.assertEqual(paper.questions.count(), 3)
        self.assertTrue(Notification.objects.filter(recipient=self.controller, title__startswith="Final paper ready").exists())

    def test_failed_background_generation_is_shown(self):
        with mock.patch.object(ai.threading, "Thread"):
            paper = ai.start_final_paper(self.bp, self.controller)
        with mock.patch.object(ai, "_ask_claude", side_effect=ai.GenerationError("Claude is busy")):
            ai.write_final_paper(paper.pk, self.controller.pk)
        paper.refresh_from_db()
        self.assertEqual(paper.generation_error, "Claude is busy")
        self.assertFalse(paper.is_generating)


@override_settings(MAKE_WEBHOOK_URL="", MAKE_MAILHOOK_ADDRESS="")
class ReminderTests(BlueprintTestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.teacher = User.objects.create_user("teacher", "teacher@example.com", "Pw-12345!", is_staff=True)
        self.teacher.user_permissions.add(Permission.objects.get(codename="add_question"))
        self.teacher = User.objects.get(pk=self.teacher.pk)
        self.bp.assigned_to, self.bp.status = self.teacher, QuestionBlueprint.Status.DRAFT
        self.bp.due_date = date.today()
        self.bp.save()

    def deadline(self, subject):
        return AcademicEvent.objects.create(title="Papers due", event_type=AcademicEvent.EventType.QUESTION_DEADLINE,
                                            start_date=date.today(), subject=subject)

    def test_deadline_reminders_only_for_their_subject(self):
        self.deadline(self.bp.subject)
        self.deadline(Subject.objects.create(name="History"))
        titles = [n.title for n in ensure_reminders(self.teacher)]
        self.assertEqual(sum("Question deadline" in t for t in titles), 1)

    def test_daily_command_emails_new_reminders_once(self):
        call_command("send_reminders", stdout=StringIO())
        self.assertEqual([m.to for m in mail.outbox], [["teacher@example.com"]])
        self.assertIn("Science mid-term", mail.outbox[0].body)
        call_command("send_reminders", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)


class ReviewTests(BlueprintTestCase):
    def test_hod_cannot_approve_own_blueprint(self):
        self.bp.status = QuestionBlueprint.Status.IN_REVIEW
        self.bp.save()
        with self.assertRaisesMessage(workflow.WorkflowError, "another HOD"):
            workflow.approve(self.bp, self.hod)
        workflow.approve(self.bp, self.controller)  # the super admin can
        self.assertEqual(self.bp.status, QuestionBlueprint.Status.APPROVED)
