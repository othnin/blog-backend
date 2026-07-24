"""
Tests for the recipes app.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from auth_app.models import UserProfile
from .models import Recipe, RecipeIngredient, RecipeInstruction, RecipeRating, DietaryLabel
import json


def _wrap_as_lexical(text):
    """Wrap plain text as Lexical JSON for tests."""
    return json.dumps({
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [
                        {"type": "text", "text": text, "format": 0}
                    ],
                    "format": ""
                }
            ],
            "type": "root",
            "format": ""
        }
    })


def make_user(username, role='editor', email=None):
    user = User.objects.create_user(
        username=username,
        password='testpass123',
        email=email or f'{username}@example.com',
    )
    user.profile.role = role
    user.profile.email_verified = True
    user.profile.save()
    return user


def auth_header(client, username, password='testpass123'):
    resp = client.post(
        '/api/token/pair',
        data=json.dumps({'username': username, 'password': password}),
        content_type='application/json',
    )
    token = resp.json()['access']
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


class DietaryLabelTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor1')
        self.headers = auth_header(self.client, 'editor1')

    def test_list_dietary_labels_public(self):
        DietaryLabel.objects.create(name='Vegan', slug='vegan')
        resp = self.client.get('/api/recipes/dietary-labels/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_create_dietary_label_editor(self):
        resp = self.client.post(
            '/api/recipes/dietary-labels/',
            data=json.dumps({'name': 'Vegan'}),
            content_type='application/json',
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Vegan')
        self.assertEqual(resp.json()['slug'], 'vegan')

    def test_create_dietary_label_unauthenticated(self):
        resp = self.client.post(
            '/api/recipes/dietary-labels/',
            data=json.dumps({'name': 'Vegan'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)


class RecipeCRUDTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor1')
        self.reader = make_user('reader1', role='reader')
        self.editor_headers = auth_header(self.client, 'editor1')
        self.reader_headers = auth_header(self.client, 'reader1')

    def _create_recipe(self, status='published', title='Pasta Carbonara'):
        payload = {
            'title': title,
            'description': _wrap_as_lexical('A classic Italian dish.'),
            'status': status,
            'ingredients': [
                {'order': 0, 'amount': '200', 'unit': 'g', 'name': 'Pasta', 'notes': ''},
                {'order': 1, 'amount': '100', 'unit': 'g', 'name': 'Pancetta', 'notes': ''},
            ],
            'instructions': [
                {'step_number': 1, 'title': 'Boil pasta', 'content': _wrap_as_lexical('Boil the pasta in salted water.')},
                {'step_number': 2, 'title': 'Fry pancetta', 'content': _wrap_as_lexical('Fry the pancetta until crispy.')},
            ],
            'prep_time_minutes': 10,
            'cook_time_minutes': 20,
            'yield_amount': '2',
            'yield_unit': 'servings',
            'cuisine_type': 'italian',
            'course': 'dinner',
        }
        return self.client.post(
            '/api/recipes/',
            data=json.dumps(payload),
            content_type='application/json',
            **self.editor_headers,
        )

    def test_create_recipe_editor(self):
        resp = self._create_recipe()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['title'], 'Pasta Carbonara')
        self.assertEqual(len(data['ingredients']), 2)
        self.assertEqual(len(data['instructions']), 2)
        self.assertEqual(data['cuisine_type'], 'italian')

    def test_create_recipe_reader_forbidden(self):
        resp = self.client.post(
            '/api/recipes/',
            data=json.dumps({'title': 'Test', 'status': 'draft'}),
            content_type='application/json',
            **self.reader_headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_list_published_recipes(self):
        self._create_recipe(status='published')
        resp = self.client.get('/api/recipes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_draft_not_in_public_list(self):
        self._create_recipe(status='draft')
        resp = self.client.get('/api/recipes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 0)

    def test_get_recipe_by_slug(self):
        self._create_recipe()
        slug = Recipe.objects.first().slug
        resp = self.client.get(f'/api/recipes/{slug}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['slug'], slug)

    def test_get_recipe_increments_view_count(self):
        self._create_recipe()
        slug = Recipe.objects.first().slug
        self.client.get(f'/api/recipes/{slug}/')
        self.client.get(f'/api/recipes/{slug}/')
        self.assertEqual(Recipe.objects.first().view_count, 2)

    def test_update_recipe(self):
        self._create_recipe()
        recipe = Recipe.objects.first()
        resp = self.client.put(
            f'/api/recipes/{recipe.id}/',
            data=json.dumps({'description': _wrap_as_lexical('Updated description')}),
            content_type='application/json',
            **self.editor_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Updated description', resp.json()['description'])

    def test_delete_recipe(self):
        self._create_recipe()
        recipe = Recipe.objects.first()
        resp = self.client.delete(
            f'/api/recipes/{recipe.id}/',
            **self.editor_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Recipe.objects.count(), 0)

    def test_my_recipes(self):
        self._create_recipe(status='draft')
        self._create_recipe(status='published', title='Another Recipe')
        resp = self.client.get('/api/recipes/my-recipes/', **self.editor_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_filter_by_cuisine(self):
        self._create_recipe()  # italian
        resp = self.client.get('/api/recipes/?cuisine=mexican')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 0)
        resp = self.client.get('/api/recipes/?cuisine=italian')
        self.assertEqual(len(resp.json()), 1)


class RecipeImageResolutionTests(TestCase):
    """Tests for recipe images serializer — resolution of bare keys and stale URLs."""

    def setUp(self):
        self.editor = make_user('editor1')
        self.recipe = Recipe.objects.create(
            author=self.editor,
            title='Test Recipe',
            slug='test-recipe',
            status='published'
        )

    def test_recipe_images_bare_key_resolved_to_url(self):
        """Recipe with bare blog_images/ key in images list resolves to a full URL in response."""
        self.recipe.images = ['blog_images/test.png']
        self.recipe.save()
        resp = self.client.get(f'/api/recipes/{self.recipe.slug}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Resolved image should be a full URL (or MEDIA_URL path in test mode)
        self.assertEqual(len(data['images']), 1)
        self.assertIsNotNone(data['images'][0])
        # Should not be the bare key anymore
        self.assertNotEqual(data['images'][0], 'blog_images/test.png')

    def test_recipe_images_null_entry_skipped(self):
        """Recipe with null/non-string image entry is filtered out (defensive for historical undefined bug)."""
        self.recipe.images = [None, 'blog_images/valid.png']
        self.recipe.save()
        resp = self.client.get(f'/api/recipes/{self.recipe.slug}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Only one image (the valid one)
        self.assertEqual(len(data['images']), 1)

    def test_recipe_images_stale_presigned_url_re_presigned(self):
        """Recipe with stale presigned URL extracts key and re-presigns fresh."""
        stale_url = 'https://t3.storageapi.dev/bucket/blog_images/old.gif?X-Amz-Date=20260723T000000Z&X-Amz-Expires=3600&X-Amz-Signature=old'
        self.recipe.images = [stale_url]
        self.recipe.save()
        resp = self.client.get(f'/api/recipes/{self.recipe.slug}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Should be resolved to a fresh URL (or MEDIA_URL in test)
        self.assertEqual(len(data['images']), 1)
        returned_url = data['images'][0]
        # Should not be the stale URL
        self.assertNotEqual(returned_url, stale_url)
        # Should contain blog_images
        self.assertIn('blog_images', returned_url)



class RecipeRatingTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor1')
        self.user2 = make_user('user2', role='reader')
        self.editor_headers = auth_header(self.client, 'editor1')
        self.user2_headers = auth_header(self.client, 'user2')
        # Create a recipe
        recipe_resp = self.client.post(
            '/api/recipes/',
            data=json.dumps({'title': 'Test Recipe', 'status': 'published'}),
            content_type='application/json',
            **self.editor_headers,
        )
        self.recipe_id = recipe_resp.json()['id']

    def test_submit_rating(self):
        resp = self.client.post(
            f'/api/recipes/{self.recipe_id}/rate/',
            data=json.dumps({'score': 4}),
            content_type='application/json',
            **self.editor_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['avg_rating'], 4.0)
        self.assertEqual(data['rating_count'], 1)
        self.assertEqual(data['user_score'], 4)

    def test_update_own_rating(self):
        self.client.post(
            f'/api/recipes/{self.recipe_id}/rate/',
            data=json.dumps({'score': 3}),
            content_type='application/json',
            **self.editor_headers,
        )
        resp = self.client.post(
            f'/api/recipes/{self.recipe_id}/rate/',
            data=json.dumps({'score': 5}),
            content_type='application/json',
            **self.editor_headers,
        )
        self.assertEqual(resp.json()['avg_rating'], 5.0)
        self.assertEqual(RecipeRating.objects.count(), 1)

    def test_invalid_rating_score(self):
        resp = self.client.post(
            f'/api/recipes/{self.recipe_id}/rate/',
            data=json.dumps({'score': 6}),
            content_type='application/json',
            **self.editor_headers,
        )
        self.assertEqual(resp.status_code, 422)

    def test_rating_requires_auth(self):
        resp = self.client.post(
            f'/api/recipes/{self.recipe_id}/rate/',
            data=json.dumps({'score': 4}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)


class RecipeCommentTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor1')
        self.editor_headers = auth_header(self.client, 'editor1')
        recipe_resp = self.client.post(
            '/api/recipes/',
            data=json.dumps({'title': 'Test Recipe', 'status': 'published'}),
            content_type='application/json',
            **self.editor_headers,
        )
        self.recipe_id = recipe_resp.json()['id']
        self.comment_json = json.dumps({'root': {'children': [{'type': 'paragraph', 'children': [{'type': 'text', 'text': 'Great recipe!'}]}]}})

    def test_create_comment(self):
        resp = self.client.post(
            f'/api/recipes/{self.recipe_id}/comments/',
            data=json.dumps({'content_json': self.comment_json}),
            content_type='application/json',
            **self.editor_headers,
        )
        self.assertEqual(resp.status_code, 200)

    def test_list_comments(self):
        self.client.post(
            f'/api/recipes/{self.recipe_id}/comments/',
            data=json.dumps({'content_json': self.comment_json}),
            content_type='application/json',
            **self.editor_headers,
        )
        resp = self.client.get(f'/api/recipes/{self.recipe_id}/comments/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_comment_requires_auth(self):
        resp = self.client.post(
            f'/api/recipes/{self.recipe_id}/comments/',
            data=json.dumps({'content_json': self.comment_json}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)
