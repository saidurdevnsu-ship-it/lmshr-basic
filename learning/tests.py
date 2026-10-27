from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from .models import Course, CourseModule, LearningActivity


def make_staff(username, *codenames):
    user = User.objects.create_user(username, password="pw", is_staff=True)
    user.user_permissions.set(
        Permission.objects.filter(content_type__app_label="learning", codename__in=codenames)
    )
    return user


AUTHOR_PERMS = (
    "view_course", "add_course", "change_course",
    "view_coursemodule", "add_coursemodule", "change_coursemodule",
    "view_learningactivity", "add_learningactivity", "change_learningactivity",
)


class CourseSlugTests(TestCase):
    def test_duplicate_titles_get_unique_slugs(self):
        author = User.objects.create_user("author")
        first = Course.objects.create(title="Intro to Python", created_by=author)
        second = Course.objects.create(title="Intro to Python", created_by=author)
        self.assertEqual(first.slug, "intro-to-python")
        self.assertEqual(second.slug, "intro-to-python-2")


class AdminScopingTests(TestCase):
    def setUp(self):
        self.alice = make_staff("alice", *AUTHOR_PERMS)
        self.bob = make_staff("bob", *AUTHOR_PERMS)
        self.alice_course = Course.objects.create(title="Alice course", created_by=self.alice)
        self.bob_course = Course.objects.create(title="Bob course", created_by=self.bob)
        self.bob_module = CourseModule.objects.create(course=self.bob_course, title="Bob module")

    def test_author_sees_only_own_courses(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("admin:learning_course_changelist"))
        self.assertContains(response, "Alice course")
        self.assertNotContains(response, "Bob course")

    def test_author_cannot_open_other_authors_module(self):
        self.client.force_login(self.alice)
        url = reverse("admin:learning_coursemodule_change", args=[self.bob_module.pk])
        response = self.client.get(url, follow=True)
        self.assertNotContains(response, "Bob module")

    def test_view_all_courses_permission_shows_everything(self):
        viewer = make_staff("viewer", "view_course", "view_all_courses")
        self.client.force_login(viewer)
        response = self.client.get(reverse("admin:learning_course_changelist"))
        self.assertContains(response, "Alice course")
        self.assertContains(response, "Bob course")


class CoursePublishingTests(TestCase):
    def setUp(self):
        self.author = make_staff("author", *AUTHOR_PERMS)
        self.publisher = make_staff("publisher", *AUTHOR_PERMS, "publish_course")
        self.course = Course.objects.create(title="Course", created_by=self.author)

    def post_status(self, user, status):
        self.client.force_login(user)
        url = reverse("admin:learning_course_change", args=[self.course.pk])
        return self.client.post(url, {
            "title": "Course",
            "slug": self.course.slug,
            "summary": "",
            "description": "",
            "status": status,
            "modules-TOTAL_FORMS": "0",
            "modules-INITIAL_FORMS": "0",
        })

    def test_author_without_publish_permission_cannot_publish(self):
        self.post_status(self.author, Course.Status.PUBLISHED)
        self.course.refresh_from_db()
        self.assertEqual(self.course.status, Course.Status.DRAFT)
        self.assertIsNone(self.course.published_at)

    def test_publisher_publishing_sets_published_at(self):
        self.course.created_by = self.publisher
        self.course.save()
        response = self.post_status(self.publisher, Course.Status.PUBLISHED)
        self.assertEqual(response.status_code, 302)
        self.course.refresh_from_db()
        self.assertEqual(self.course.status, Course.Status.PUBLISHED)
        self.assertIsNotNone(self.course.published_at)


class ActivityInlineTests(TestCase):
    def setUp(self):
        self.author = make_staff("author", *AUTHOR_PERMS)
        course = Course.objects.create(title="Course", created_by=self.author)
        self.module = CourseModule.objects.create(course=course, title="Module")
        self.client.force_login(self.author)
        self.url = reverse("admin:learning_coursemodule_change", args=[self.module.pk])

    def post_activity(self, **activity):
        data = {
            "course": str(self.module.course.pk),
            "title": "Module",
            "description": "",
            "position": "1",
            "activities-TOTAL_FORMS": "1",
            "activities-INITIAL_FORMS": "0",
            "activities-0-title": "Lesson",
            "activities-0-position": "1",
        }
        data.update({f"activities-0-{key}": value for key, value in activity.items()})
        return self.client.post(self.url, data)

    def test_add_video_activity_via_inline(self):
        response = self.post_activity(activity_type="video", resource_url="https://example.com/v")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(LearningActivity.objects.filter(module=self.module, title="Lesson").exists())

    def test_missing_resource_url_shows_error_instead_of_crashing(self):
        response = self.post_activity(activity_type="video")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This activity type needs a resource URL.")
        self.assertFalse(LearningActivity.objects.exists())

    def test_text_activity_requires_body(self):
        response = self.post_activity(activity_type="text")
        self.assertContains(response, "Text lessons need lesson content.")
