from django.test import TestCase, Client
from thales.models import Lesson, StudentProgress, AssistantInteraction, ModelExperiment
from thales.molecular_data import get_base, is_purine, is_pyrimidine, get_all_bases
from thales.validation import MolecularValidator
import json


class LessonModelTest(TestCase):
    def test_lesson_creation(self):
        lesson = Lesson.objects.create(
            title="Meet the Bases",
            description="Learn about A, T, G, C",
            mode=Lesson.CLASSROOM,
            sequence_order=1,
            content_json={"objectives": ["Identify purines and pyrimidines"]}
        )
        self.assertEqual(lesson.title, "Meet the Bases")
        self.assertEqual(lesson.mode, Lesson.CLASSROOM)

    def test_lesson_str(self):
        lesson = Lesson.objects.create(
            title="Test",
            mode=Lesson.MYSTERY,
            sequence_order=1
        )
        self.assertIn("Watson & Crick", str(lesson))

    def test_lesson_ordering(self):
        lesson1 = Lesson.objects.create(title="First", mode=Lesson.CLASSROOM, sequence_order=2)
        lesson2 = Lesson.objects.create(title="Second", mode=Lesson.CLASSROOM, sequence_order=1)
        lessons = list(Lesson.objects.all())
        self.assertEqual(lessons[0].sequence_order, 1)


class StudentProgressTest(TestCase):
    def test_progress_creation(self):
        lesson = Lesson.objects.create(title="Test", mode=Lesson.CLASSROOM, sequence_order=1)
        progress = StudentProgress.objects.create(
            session_id="test_session_001",
            current_lesson=lesson
        )
        self.assertEqual(progress.session_id, "test_session_001")
        self.assertEqual(progress.current_lesson, lesson)

    def test_progress_without_lesson(self):
        progress = StudentProgress.objects.create(session_id="test_session_002")
        self.assertIsNone(progress.current_lesson)


class AssistantInteractionTest(TestCase):
    def test_interaction_logging(self):
        progress = StudentProgress.objects.create(session_id="test_session_003")
        interaction = AssistantInteraction.objects.create(
            progress=progress,
            question="Why does A pair with T?",
            response="Compare their molecular sizes.",
            response_type='hint',
            hint_level=1,
            simulation_year=1952,
            mode=Lesson.MYSTERY
        )
        self.assertEqual(interaction.hint_level, 1)
        self.assertTrue(interaction.spoiler_safe)

    def test_interaction_types(self):
        progress = StudentProgress.objects.create(session_id="test_session_004")
        for response_type, _ in AssistantInteraction.RESPONSE_TYPES:
            interaction = AssistantInteraction.objects.create(
                progress=progress,
                question="test",
                response="test",
                response_type=response_type,
                simulation_year=1952,
                mode=Lesson.CLASSROOM
            )
            self.assertEqual(interaction.response_type, response_type)


class ModelExperimentTest(TestCase):
    def test_experiment_creation(self):
        progress = StudentProgress.objects.create(session_id="test_session_005")
        experiment = ModelExperiment.objects.create(
            progress=progress,
            left_base='A',
            right_base='T',
            validity_json={'valid': True}
        )
        self.assertEqual(experiment.left_base, 'A')
        self.assertEqual(experiment.right_base, 'T')

    def test_experiment_cascading_delete(self):
        progress = StudentProgress.objects.create(session_id="test_session_006")
        ModelExperiment.objects.create(progress=progress, left_base='G', right_base='C')
        progress.delete()
        self.assertEqual(ModelExperiment.objects.count(), 0)


class MolecularDataTest(TestCase):
    def test_load_adenine(self):
        adenine = get_base('A')
        self.assertEqual(adenine['symbol'], 'A')
        self.assertEqual(adenine['category'], 'purine')
        self.assertGreater(len(adenine['atoms']), 0)
        self.assertGreater(len(adenine['bonds']), 0)

    def test_load_thymine(self):
        thymine = get_base('T')
        self.assertEqual(thymine['symbol'], 'T')
        self.assertEqual(thymine['category'], 'pyrimidine')

    def test_load_guanine(self):
        guanine = get_base('G')
        self.assertEqual(guanine['symbol'], 'G')
        self.assertEqual(guanine['category'], 'purine')

    def test_load_cytosine(self):
        cytosine = get_base('C')
        self.assertEqual(cytosine['symbol'], 'C')
        self.assertEqual(cytosine['category'], 'pyrimidine')

    def test_invalid_base(self):
        with self.assertRaises(ValueError):
            get_base('X')

    def test_purine_check(self):
        self.assertTrue(is_purine('A'))
        self.assertTrue(is_purine('G'))
        self.assertFalse(is_purine('T'))
        self.assertFalse(is_purine('C'))

    def test_pyrimidine_check(self):
        self.assertTrue(is_pyrimidine('T'))
        self.assertTrue(is_pyrimidine('C'))
        self.assertFalse(is_pyrimidine('A'))
        self.assertFalse(is_pyrimidine('G'))

    def test_all_bases(self):
        all_bases = get_all_bases()
        self.assertEqual(len(all_bases), 4)
        self.assertIn('adenine', all_bases)
        self.assertIn('thymine', all_bases)
        self.assertIn('guanine', all_bases)
        self.assertIn('cytosine', all_bases)


class MolecularValidationTest(TestCase):
    def test_adenine_thymine_pairing(self):
        result = MolecularValidator.validate_base_pair('A', 'T')
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['reasons']), 0)
        self.assertEqual(result['observations']['left_category'], 'purine')
        self.assertEqual(result['observations']['right_category'], 'pyrimidine')

    def test_guanine_cytosine_pairing(self):
        result = MolecularValidator.validate_base_pair('G', 'C')
        self.assertTrue(result['valid'])

    def test_thymine_adenine_pairing(self):
        result = MolecularValidator.validate_base_pair('T', 'A')
        self.assertTrue(result['valid'])

    def test_cytosine_guanine_pairing(self):
        result = MolecularValidator.validate_base_pair('C', 'G')
        self.assertTrue(result['valid'])

    def test_invalid_purine_purine(self):
        result = MolecularValidator.validate_base_pair('A', 'G')
        self.assertFalse(result['valid'])
        self.assertIn('pair_width_inconsistent', result['reasons'])

    def test_invalid_pyrimidine_pyrimidine(self):
        result = MolecularValidator.validate_base_pair('T', 'C')
        self.assertFalse(result['valid'])
        self.assertIn('pair_width_inconsistent', result['reasons'])

    def test_validate_complementary_list(self):
        pairs = [('A', 'T'), ('G', 'C'), ('T', 'A')]
        result = MolecularValidator.validate_complementary_pairing(pairs)
        self.assertTrue(result['valid'])
        self.assertEqual(result['valid_pairs'], 3)
        self.assertEqual(result['total_pairs'], 3)

    def test_validate_mixed_list(self):
        pairs = [('A', 'T'), ('A', 'G'), ('G', 'C')]
        result = MolecularValidator.validate_complementary_pairing(pairs)
        self.assertFalse(result['valid'])
        self.assertEqual(result['valid_pairs'], 2)
        self.assertEqual(len(result['failures']), 1)

    def test_invalid_a_c_pairing(self):
        result = MolecularValidator.validate_base_pair('A', 'C')
        self.assertFalse(result['valid'])
        self.assertIn('invalid_base_pair', result['reasons'])

    def test_invalid_g_t_pairing(self):
        result = MolecularValidator.validate_base_pair('G', 'T')
        self.assertFalse(result['valid'])
        self.assertIn('invalid_base_pair', result['reasons'])


class ThalesAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        # Create test lesson
        self.lesson = Lesson.objects.create(
            title="Test Lesson",
            description="Test",
            mode=Lesson.CLASSROOM,
            sequence_order=1
        )

    def test_get_molecular_data(self):
        response = self.client.get('/api/thales/molecular-data/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('bases', data)
        self.assertIn('adenine', data['bases'])
        self.assertIn('thymine', data['bases'])
        self.assertIn('guanine', data['bases'])
        self.assertIn('cytosine', data['bases'])

    def test_validate_model_endpoint(self):
        response = self.client.post('/api/thales/model/validate/',
            data=json.dumps({'left_base': 'A', 'right_base': 'T'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['valid'])

    def test_get_progress(self):
        response = self.client.get('/api/thales/progress/?session_id=test123')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['session_id'], 'test123')

    def test_list_lessons(self):
        response = self.client.get('/api/thales/lessons/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['title'], 'Test Lesson')
