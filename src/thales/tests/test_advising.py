import json

from django.conf import settings
from django.test import Client, TestCase

from thales.models import (
    AdvisorFeedback,
    AssistantInteraction,
    HypothesisNote,
    Lesson,
    ModelExperiment,
    StudentGrade,
    StudentProgress,
)
from thales.tests.utils import (
    advisor_group_has_permission,
    authenticate,
    make_thales_user,
    thales_group_has_permission,
)


class AdvisorAccessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.lesson = Lesson.objects.create(
            title='Test Lesson',
            description='Test',
            mode=Lesson.CLASSROOM,
            sequence_order=1,
        )
        self.student = make_thales_user('student')
        self.advisor = make_thales_user('advisor', advisor=True)
        self.admin = make_thales_user('site-admin', role='admin', thales=False)
        StudentProgress.objects.create(
            session_id='student-session',
            user_id=self.student.id,
            username=self.student.username,
            current_lesson=self.lesson,
        )

    def test_advisor_group_has_both_permissions(self):
        self.assertTrue(advisor_group_has_permission())
        self.assertTrue(thales_group_has_permission())

    def test_advisor_page_redirects_anonymous_user(self):
        response = self.client.get('/thales/advisor/')

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(settings.FRONTEND_URL.rstrip('/')))
        self.assertIn('/login?next=/thales/advisor/', response.url)

    def test_advisor_page_denies_ordinary_lab_member(self):
        authenticate(self.client, self.student)

        self.assertEqual(self.client.get('/thales/advisor/').status_code, 403)

    def test_advisor_page_allows_advisor(self):
        authenticate(self.client, self.advisor)

        self.assertEqual(self.client.get('/thales/advisor/').status_code, 200)

    def test_advisor_page_allows_admin_without_group(self):
        authenticate(self.client, self.admin)

        self.assertEqual(self.client.get('/thales/advisor/').status_code, 200)

    def test_me_reports_advisor_capability(self):
        authenticate(self.client, self.student)
        self.assertFalse(self.client.get('/api/thales/me/').json()['is_advisor'])

        other_client = Client()
        authenticate(other_client, self.advisor)
        body = other_client.get('/api/thales/me/').json()
        self.assertTrue(body['is_advisor'])
        self.assertEqual(body['username'], 'advisor')

    def test_ordinary_member_cannot_read_advisor_roster(self):
        authenticate(self.client, self.student)

        response = self.client.get('/api/thales/advising/students/')

        self.assertEqual(response.status_code, 403)

    def test_advisor_is_a_separate_capability_not_a_profile_role(self):
        self.assertEqual(self.advisor.profile.role, 'reader')
        self.assertTrue(self.advisor.has_perm('thales.advise_students'))
        self.assertTrue(self.advisor.has_perm('thales.access_thales'))


class AdvisorRecordsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.student_client = Client()
        self.other_student_client = Client()

        self.lesson = Lesson.objects.create(
            title='Meet the Bases',
            description='Test',
            mode=Lesson.CLASSROOM,
            sequence_order=1,
        )
        self.student = make_thales_user('student')
        self.other_student = make_thales_user('other-student')
        self.advisor = make_thales_user('advisor', advisor=True)
        authenticate(self.client, self.advisor)
        authenticate(self.student_client, self.student)
        authenticate(self.other_student_client, self.other_student)

        self.progress = StudentProgress.objects.create(
            session_id='student-session',
            user_id=self.student.id,
            username=self.student.username,
            current_lesson=self.lesson,
            state_json={'unlocked': ['photo-51']},
        )
        self.progress.completed_lessons.add(self.lesson)
        self.experiment = ModelExperiment.objects.create(
            progress=self.progress,
            username=self.student.username,
            left_base='A',
            right_base='T',
            validity_json={'valid': True},
        )
        self.interaction = AssistantInteraction.objects.create(
            progress=self.progress,
            username=self.student.username,
            question='Why A-T?',
            response='Compare the geometry.',
            response_type='hint',
            hint_level=1,
            simulation_year=1952,
            mode=Lesson.MYSTERY,
        )
        self.hypothesis = HypothesisNote.objects.create(
            user_id=self.student.id,
            username=self.student.username,
            text='A pairs with T.',
        )

    def test_advisor_roster_includes_records_and_grade(self):
        response = self.client.get('/api/thales/advising/students/')

        self.assertEqual(response.status_code, 200)
        students = response.json()['students']
        self.assertEqual(len(students), 1)
        student = students[0]
        self.assertEqual(student['user_id'], self.student.id)
        self.assertEqual(student['username'], 'student')
        self.assertEqual(student['current_lesson'], 'Meet the Bases')
        self.assertEqual(student['experiment_count'], 1)
        self.assertEqual(student['question_count'], 1)
        self.assertEqual(student['progress_count'], 1)
        self.assertIsNone(student['grade'])

    def test_advisor_detail_contains_progress_experiments_and_interactions(self):
        response = self.client.get(
            f'/api/thales/advising/students/{self.student.id}/'
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['username'], 'student')
        self.assertEqual(len(body['progress']), 1)
        self.assertEqual(body['progress'][0]['completed_lessons'][0]['title'], 'Meet the Bases')
        self.assertEqual(body['experiments'][0]['left_base'], 'A')
        self.assertEqual(body['interactions'][0]['question'], 'Why A-T?')
        self.assertEqual(body['hypothesis']['text'], 'A pairs with T.')
        self.assertIsNone(body['grade'])

    def test_advisor_can_set_and_replace_grade(self):
        response = self.client.put(
            f'/api/thales/advising/students/{self.student.id}/grade/',
            data=json.dumps({'grade': 'B+'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['grade'], 'B+')

        response = self.client.put(
            f'/api/thales/advising/students/{self.student.id}/grade/',
            data=json.dumps({'grade': 'A-'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentGrade.objects.count(), 1)
        grade = StudentGrade.objects.get(student_user_id=self.student.id)
        self.assertEqual(grade.grade, 'A-')
        self.assertEqual(grade.graded_by_username, 'advisor')

        detail = self.client.get(
            f'/api/thales/advising/students/{self.student.id}/'
        ).json()
        self.assertEqual(detail['grade']['grade'], 'A-')

    def test_advisor_can_clear_grade_with_an_empty_value(self):
        StudentGrade.objects.create(
            student_user_id=self.student.id,
            student_username=self.student.username,
            grade='B',
        )

        response = self.client.put(
            f'/api/thales/advising/students/{self.student.id}/grade/',
            data=json.dumps({'grade': '  '}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['grade'])
        self.assertFalse(
            StudentGrade.objects.filter(student_user_id=self.student.id).exists()
        )

    def test_feedback_is_visible_to_the_target_student(self):
        response = self.client.post(
            f'/api/thales/advising/students/{self.student.id}/feedback/',
            data=json.dumps({'text': 'Your A-T reasoning is solid.'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['advisor_username'], 'advisor')

        response = self.student_client.get('/api/thales/feedback/')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['feedback']), 1)
        self.assertEqual(body['feedback'][0]['text'], 'Your A-T reasoning is solid.')
        self.assertEqual(body['feedback'][0]['advisor_username'], 'advisor')

    def test_feedback_is_not_visible_to_other_students(self):
        AdvisorFeedback.objects.create(
            student_user_id=self.student.id,
            student_username=self.student.username,
            advisor_id=self.advisor.id,
            advisor_username=self.advisor.username,
            text='Private note for student.',
        )

        response = self.other_student_client.get('/api/thales/feedback/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['feedback'], [])

    def test_student_feedback_never_contains_grade(self):
        self.client.put(
            f'/api/thales/advising/students/{self.student.id}/grade/',
            data=json.dumps({'grade': 'A'}),
            content_type='application/json',
        )
        self.client.post(
            f'/api/thales/advising/students/{self.student.id}/feedback/',
            data=json.dumps({'text': 'Strong work.'}),
            content_type='application/json',
        )

        response = self.student_client.get('/api/thales/feedback/')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('grade', response.content.decode().lower())

    def test_student_cannot_read_the_advisor_detail(self):
        response = self.student_client.get(
            f'/api/thales/advising/students/{self.student.id}/'
        )

        self.assertEqual(response.status_code, 403)

    def test_feedback_requires_non_blank_text(self):
        response = self.client.post(
            f'/api/thales/advising/students/{self.student.id}/feedback/',
            data=json.dumps({'text': '   '}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AdvisorFeedback.objects.count(), 0)

    def test_advising_endpoints_404_for_unknown_student(self):
        self.assertEqual(
            self.client.get('/api/thales/advising/students/999999/').status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                '/api/thales/advising/students/999999/feedback/',
                data=json.dumps({'text': 'Hello'}),
                content_type='application/json',
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.put(
                '/api/thales/advising/students/999999/grade/',
                data=json.dumps({'grade': 'A'}),
                content_type='application/json',
            ).status_code,
            404,
        )

    def test_admin_can_use_the_advisor_api_without_the_group(self):
        admin_client = Client()
        admin = make_thales_user('admin-user', role='admin', thales=False)
        authenticate(admin_client, admin)

        response = admin_client.get('/api/thales/advising/students/')

        self.assertEqual(response.status_code, 200)
