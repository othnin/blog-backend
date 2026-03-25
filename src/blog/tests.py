"""
Unit tests for blog endpoints, models, and utilities.

Authentication note: the blog controller uses auth=JWTAuth() on all protected
endpoints.  Tests obtain a real JWT token via POST /api/token/pair and send it
via HTTP_AUTHORIZATION on every request using the JWTClient helper.
Unauthenticated requests return 401 (JWTAuth rejects before any permission check).
Authenticated-but-unauthorised requests return 403 (IsEditorOrAdmin permission).
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
import json

from blog.models import BlogPost, Category, Comment
from blog.utils import create_unique_slug, can_edit_post, can_delete_post


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

LEXICAL_JSON = json.dumps({
    "root": {
        "children": [{
            "children": [{
                "detail": 0, "format": 0, "mode": "normal",
                "style": "", "text": "Hello world",
                "type": "text", "version": 1
            }],
            "direction": "ltr", "format": "", "indent": 0,
            "type": "paragraph", "version": 1
        }],
        "direction": "ltr", "format": "", "indent": 0,
        "type": "root", "version": 1
    }
})


def make_user(username, email, password='ValidPass123', role='reader', email_verified=True):
    """Create a User with a profile."""
    user = User.objects.create_user(username=username, email=email, password=password)
    user.profile.role = role
    user.profile.email_verified = email_verified
    user.profile.save()
    return user


def make_post(title, author, status='draft', slug=None):
    """Create a BlogPost with minimal required fields."""
    if slug is None:
        slug = title.lower().replace(' ', '-').replace("'", '')
    return BlogPost.objects.create(
        title=title, slug=slug,
        author=author, content_json=LEXICAL_JSON, status=status,
    )


class JWTClient(Client):
    """Django test client that injects a Bearer JWT token on every request."""

    def __init__(self, token, **kwargs):
        super().__init__(**kwargs)
        self._jwt_token = token

    def _base_environ(self, **request):
        environ = super()._base_environ(**request)
        environ.setdefault('HTTP_AUTHORIZATION', f'Bearer {self._jwt_token}')
        return environ


def jwt_client(user, password='ValidPass123'):
    """Return a JWTClient authenticated as *user*."""
    c = Client()
    resp = c.post(
        '/api/token/pair',
        data=json.dumps({'username': user.username, 'password': password}),
        content_type='application/json',
    )
    token = json.loads(resp.content)['access']
    return JWTClient(token=token)


# ---------------------------------------------------------------------------
# Category Tests
# ---------------------------------------------------------------------------

class CategoryTests(TestCase):
    """Tests for GET /api/blog/categories/ and POST /api/blog/categories/"""

    def setUp(self):
        self.client = Client()
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        Category.objects.create(name='Technology', slug='technology')
        Category.objects.create(name='Science', slug='science')

    def test_list_is_public(self):
        response = self.client.get('/api/blog/categories/')
        self.assertEqual(response.status_code, 200)

    def test_list_returns_all_categories(self):
        response = self.client.get('/api/blog/categories/')
        data = json.loads(response.content)
        self.assertEqual(len(data), 2)

    def test_response_includes_name_and_slug(self):
        response = self.client.get('/api/blog/categories/')
        data = json.loads(response.content)
        slugs = {c['slug'] for c in data}
        names = {c['name'] for c in data}
        self.assertIn('technology', slugs)
        self.assertIn('Technology', names)

    def test_category_auto_slug_on_save(self):
        cat = Category.objects.create(name='My New Category')
        self.assertEqual(cat.slug, 'my-new-category')

    def test_category_slug_uniqueness_enforced(self):
        with self.assertRaises(Exception):
            Category.objects.create(name='Duplicate', slug='technology')

    def test_editor_can_create_category(self):
        client = jwt_client(self.editor)
        response = client.post(
            '/api/blog/categories/',
            data=json.dumps({'name': 'New Category'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['name'], 'New Category')

    def test_unauthenticated_cannot_create_category(self):
        response = self.client.post(
            '/api/blog/categories/',
            data=json.dumps({'name': 'Sneaky'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)


# ---------------------------------------------------------------------------
# Blog Post List Tests
# ---------------------------------------------------------------------------

class BlogPostListTests(TestCase):
    """Tests for GET /api/blog/posts/"""

    def setUp(self):
        self.client = Client()
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        make_post('Published Post', self.editor, status='published', slug='published-post')
        make_post('Draft Post', self.editor, status='draft', slug='draft-post')
        make_post('Archived Post', self.editor, status='archived', slug='archived-post')

    def test_list_is_public(self):
        response = self.client.get('/api/blog/posts/')
        self.assertEqual(response.status_code, 200)

    def test_list_returns_published_only(self):
        response = self.client.get('/api/blog/posts/')
        data = json.loads(response.content)
        titles = {p['title'] for p in data}
        self.assertIn('Published Post', titles)
        self.assertNotIn('Draft Post', titles)
        self.assertNotIn('Archived Post', titles)

    def test_list_includes_author_and_categories(self):
        response = self.client.get('/api/blog/posts/')
        data = json.loads(response.content)
        self.assertTrue(len(data) > 0)
        post = data[0]
        self.assertIn('author', post)
        self.assertIn('categories', post)

    def test_list_limit_parameter(self):
        for i in range(5):
            make_post(f'Extra {i}', self.editor, status='published', slug=f'extra-{i}')
        response = self.client.get('/api/blog/posts/?limit=2')
        data = json.loads(response.content)
        self.assertEqual(len(data), 2)

    def test_search_by_title(self):
        response = self.client.get('/api/blog/posts/?search=Published')
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['title'], 'Published Post')

    def test_search_no_match_returns_empty(self):
        response = self.client.get('/api/blog/posts/?search=xyznotfound')
        data = json.loads(response.content)
        self.assertEqual(len(data), 0)


# ---------------------------------------------------------------------------
# Blog Post Detail Tests
# ---------------------------------------------------------------------------

class BlogPostDetailTests(TestCase):
    """Tests for GET /api/blog/posts/{slug}/"""

    def setUp(self):
        self.client = Client()
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        self.published = make_post('Published Post', self.editor, status='published', slug='published-post')
        self.draft = make_post('Draft Post', self.editor, status='draft', slug='draft-post')

    def test_get_published_post_by_slug(self):
        response = self.client.get('/api/blog/posts/published-post/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['title'], 'Published Post')
        self.assertEqual(data['slug'], 'published-post')

    def test_get_post_increments_view_count(self):
        initial = self.published.view_count
        self.client.get('/api/blog/posts/published-post/')
        self.published.refresh_from_db()
        self.assertEqual(self.published.view_count, initial + 1)

    def test_nonexistent_slug_returns_404(self):
        response = self.client.get('/api/blog/posts/does-not-exist/')
        self.assertEqual(response.status_code, 404)

    def test_draft_post_returns_404_publicly(self):
        response = self.client.get('/api/blog/posts/draft-post/')
        self.assertEqual(response.status_code, 404)

    def test_response_includes_content_and_author(self):
        response = self.client.get('/api/blog/posts/published-post/')
        data = json.loads(response.content)
        self.assertIn('content_json', data)
        self.assertIn('author', data)
        self.assertIn('view_count', data)

    def test_author_avatar_url_field_present(self):
        """BlogPostAuthorOut must always include avatar_url (null when unset)."""
        response = self.client.get('/api/blog/posts/published-post/')
        data = json.loads(response.content)
        self.assertIn('avatar_url', data['author'])

    def test_author_avatar_url_is_none_without_upload(self):
        response = self.client.get('/api/blog/posts/published-post/')
        data = json.loads(response.content)
        self.assertIsNone(data['author']['avatar_url'])


# ---------------------------------------------------------------------------
# Blog Post Create Tests
# ---------------------------------------------------------------------------

class BlogPostCreateTests(TestCase):
    """Tests for POST /api/blog/posts/"""

    def setUp(self):
        self.reader = make_user('reader', 'reader@example.com', role='reader')
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        self.admin = make_user('admin_user', 'admin@example.com', role='admin')
        self.url = '/api/blog/posts/'
        self.valid_data = {'title': 'My New Post', 'content_json': LEXICAL_JSON}

    def _post(self, data, user=None):
        client = jwt_client(user) if user else Client()
        return client.post(self.url, data=json.dumps(data), content_type='application/json')

    def test_editor_can_create_post(self):
        response = self._post(self.valid_data, self.editor)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['title'], 'My New Post')
        self.assertEqual(data['author']['username'], 'editor')

    def test_admin_can_create_post(self):
        response = self._post(self.valid_data, self.admin)
        self.assertEqual(response.status_code, 200)

    def test_reader_cannot_create_post(self):
        response = self._post(self.valid_data, self.reader)
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_cannot_create_post(self):
        response = self._post(self.valid_data)
        self.assertEqual(response.status_code, 401)

    def test_default_status_is_draft(self):
        response = self._post(self.valid_data, self.editor)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'draft')

    def test_can_create_as_published(self):
        data = {**self.valid_data, 'status': 'published'}
        response = self._post(data, self.editor)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(result['status'], 'published')
        self.assertIsNotNone(result['published_at'])

    def test_invalid_content_json_rejected(self):
        data = {**self.valid_data, 'content_json': 'not { valid json'}
        response = self._post(data, self.editor)
        self.assertNotEqual(response.status_code, 200)

    def test_invalid_status_rejected(self):
        data = {**self.valid_data, 'status': 'unknown-status'}
        response = self._post(data, self.editor)
        self.assertNotEqual(response.status_code, 200)

    def test_create_with_categories(self):
        cat = Category.objects.create(name='Tech', slug='tech')
        data = {**self.valid_data, 'category_ids': [cat.id]}
        response = self._post(data, self.editor)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result['categories']), 1)
        self.assertEqual(result['categories'][0]['slug'], 'tech')

    def test_duplicate_title_gets_unique_slug(self):
        self._post(self.valid_data, self.editor)
        response = self._post(self.valid_data, self.editor)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertNotEqual(result['slug'], 'my-new-post')

    def test_empty_title_rejected(self):
        data = {'title': '', 'content_json': LEXICAL_JSON}
        response = self._post(data, self.editor)
        self.assertNotEqual(response.status_code, 200)

    def test_response_includes_avatar_url(self):
        """Created post response must include author.avatar_url."""
        response = self._post(self.valid_data, self.editor)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('avatar_url', data['author'])


# ---------------------------------------------------------------------------
# Blog Post Update Tests
# ---------------------------------------------------------------------------

class BlogPostUpdateTests(TestCase):
    """Tests for PUT /api/blog/posts/{post_id}/"""

    def setUp(self):
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        self.other_editor = make_user('other', 'other@example.com', role='editor')
        self.admin = make_user('admin_user', 'admin@example.com', role='admin')
        self.post = make_post('Original Title', self.editor, slug='original-title')

    def _put(self, data, user=None, post_id=None):
        pid = post_id or self.post.id
        client = jwt_client(user) if user else Client()
        return client.put(f'/api/blog/posts/{pid}/', data=json.dumps(data), content_type='application/json')

    def test_owner_can_update_own_post(self):
        response = self._put({'title': 'Updated Title'}, self.editor)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['title'], 'Updated Title')

    def test_non_owner_editor_cannot_update_post(self):
        response = self._put({'title': 'Hijacked'}, self.other_editor)
        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_any_post(self):
        response = self._put({'title': 'Admin Updated'}, self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['title'], 'Admin Updated')

    def test_unauthenticated_cannot_update(self):
        response = self._put({'title': 'Unauthorized'})
        self.assertEqual(response.status_code, 401)

    def test_publishing_sets_published_at(self):
        response = self._put({'status': 'published'}, self.editor)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(result['status'], 'published')
        self.assertIsNotNone(result['published_at'])

    def test_update_nonexistent_post_returns_error(self):
        response = self._put({'title': 'Ghost'}, self.admin, post_id=99999)
        self.assertNotEqual(response.status_code, 200)

    def test_update_categories(self):
        cat = Category.objects.create(name='NewCat', slug='newcat')
        response = self._put({'category_ids': [cat.id]}, self.editor)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result['categories']), 1)
        self.assertEqual(result['categories'][0]['slug'], 'newcat')

    def test_update_content_json(self):
        new_content = json.dumps({"root": {"type": "root", "children": []}})
        response = self._put({'content_json': new_content}, self.editor)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['content_json'], new_content)


# ---------------------------------------------------------------------------
# Blog Post Delete Tests
# ---------------------------------------------------------------------------

class BlogPostDeleteTests(TestCase):
    """Tests for DELETE /api/blog/posts/{post_id}/"""

    def setUp(self):
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        self.other_editor = make_user('other', 'other@example.com', role='editor')
        self.admin = make_user('admin_user', 'admin@example.com', role='admin')
        self.reader = make_user('reader', 'reader@example.com', role='reader')

    def _new_post(self, author=None):
        author = author or self.editor
        n = BlogPost.objects.count()
        return make_post(f'Delete Post {n}', author, slug=f'delete-post-{n}')

    def test_owner_can_delete_own_post(self):
        post = self._new_post(self.editor)
        response = jwt_client(self.editor).delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BlogPost.objects.filter(id=post.id).exists())

    def test_non_owner_cannot_delete_post(self):
        post = self._new_post(self.editor)
        response = jwt_client(self.other_editor).delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 403)
        self.assertTrue(BlogPost.objects.filter(id=post.id).exists())

    def test_admin_can_delete_any_post(self):
        post = self._new_post(self.editor)
        response = jwt_client(self.admin).delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BlogPost.objects.filter(id=post.id).exists())

    def test_unauthenticated_cannot_delete_post(self):
        post = self._new_post()
        response = Client().delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 401)
        self.assertTrue(BlogPost.objects.filter(id=post.id).exists())

    def test_delete_nonexistent_post_returns_404(self):
        response = jwt_client(self.admin).delete('/api/blog/posts/99999/')
        self.assertEqual(response.status_code, 404)

    def test_reader_cannot_delete_post(self):
        post = self._new_post(self.editor)
        response = jwt_client(self.reader).delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# My Posts Tests
# ---------------------------------------------------------------------------

class MyPostsTests(TestCase):
    """Tests for GET /api/blog/my-posts/"""

    def setUp(self):
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        self.other = make_user('other', 'other@example.com', role='editor')

        make_post('My Draft', self.editor, status='draft', slug='my-draft')
        make_post('My Published', self.editor, status='published', slug='my-published')
        make_post('Others Post', self.other, status='published', slug='others-post')

    def test_authenticated_gets_own_posts(self):
        response = jwt_client(self.editor).get('/api/blog/my-posts/')
        self.assertEqual(response.status_code, 200)
        titles = {p['title'] for p in json.loads(response.content)}
        self.assertIn('My Draft', titles)
        self.assertIn('My Published', titles)
        self.assertNotIn('Others Post', titles)

    def test_includes_drafts(self):
        response = jwt_client(self.editor).get('/api/blog/my-posts/')
        statuses = {p['status'] for p in json.loads(response.content)}
        self.assertIn('draft', statuses)

    def test_unauthenticated_returns_401(self):
        response = Client().get('/api/blog/my-posts/')
        self.assertEqual(response.status_code, 401)

    def test_each_user_sees_only_their_posts(self):
        response = jwt_client(self.other).get('/api/blog/my-posts/')
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['title'], 'Others Post')


# ---------------------------------------------------------------------------
# Comment Tests
# ---------------------------------------------------------------------------

class CommentTests(TestCase):
    """Tests for /api/blog/posts/{post_id}/comments/ and /api/blog/comments/{id}/"""

    def setUp(self):
        self.reader = make_user('reader', 'reader@example.com', role='reader')
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        self.admin = make_user('admin_user', 'admin@example.com', role='admin')
        self.other = make_user('other', 'other@example.com', role='reader')
        self.post = make_post('Test Post', self.editor, status='published', slug='test-post')

    def _comments_url(self):
        return f'/api/blog/posts/{self.post.id}/comments/'

    def _comment_url(self, cid):
        return f'/api/blog/comments/{cid}/'

    def _create_comment(self, user, content=None, parent_id=None):
        payload = {'content_json': content or LEXICAL_JSON}
        if parent_id:
            payload['parent_id'] = parent_id
        return jwt_client(user).post(
            self._comments_url(),
            data=json.dumps(payload),
            content_type='application/json',
        )

    # ── List ──────────────────────────────────────────────────────────────

    def test_list_comments_is_public(self):
        response = Client().get(self._comments_url())
        self.assertEqual(response.status_code, 200)

    def test_list_returns_empty_list_when_no_comments(self):
        response = Client().get(self._comments_url())
        self.assertEqual(json.loads(response.content), [])

    def test_list_returns_existing_comments(self):
        self._create_comment(self.reader)
        response = Client().get(self._comments_url())
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)

    def test_list_for_nonexistent_post_returns_404(self):
        response = Client().get('/api/blog/posts/99999/comments/')
        self.assertEqual(response.status_code, 404)

    # ── Create ────────────────────────────────────────────────────────────

    def test_authenticated_can_create_comment(self):
        response = self._create_comment(self.reader)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['author']['username'], 'reader')
        self.assertFalse(data['is_deleted'])

    def test_unauthenticated_cannot_create_comment(self):
        response = Client().post(
            self._comments_url(),
            data=json.dumps({'content_json': LEXICAL_JSON}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    def test_comment_on_nonexistent_post_returns_404(self):
        response = jwt_client(self.reader).post(
            '/api/blog/posts/99999/comments/',
            data=json.dumps({'content_json': LEXICAL_JSON}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)

    def test_reply_creates_nested_comment(self):
        parent_resp = self._create_comment(self.reader)
        parent_id = json.loads(parent_resp.content)['id']

        reply_resp = self._create_comment(self.other, parent_id=parent_id)
        self.assertEqual(reply_resp.status_code, 200)

        # The reply should appear nested under parent in the tree
        tree = json.loads(Client().get(self._comments_url()).content)
        self.assertEqual(len(tree), 1)
        self.assertEqual(len(tree[0]['replies']), 1)
        self.assertEqual(tree[0]['replies'][0]['author']['username'], 'other')

    def test_reply_to_nonexistent_parent_returns_404(self):
        response = jwt_client(self.reader).post(
            self._comments_url(),
            data=json.dumps({'content_json': LEXICAL_JSON, 'parent_id': 99999}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)

    def test_comment_author_includes_avatar_url(self):
        resp = self._create_comment(self.reader)
        data = json.loads(resp.content)
        self.assertIn('avatar_url', data['author'])

    # ── Edit ──────────────────────────────────────────────────────────────

    def test_owner_can_edit_own_comment(self):
        comment_id = json.loads(self._create_comment(self.reader).content)['id']
        new_content = json.dumps({"root": {"type": "root", "children": []}})
        response = jwt_client(self.reader).put(
            self._comment_url(comment_id),
            data=json.dumps({'content_json': new_content}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['content_json'], new_content)

    def test_non_owner_cannot_edit_comment(self):
        comment_id = json.loads(self._create_comment(self.reader).content)['id']
        response = jwt_client(self.other).put(
            self._comment_url(comment_id),
            data=json.dumps({'content_json': LEXICAL_JSON}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_cannot_edit_comment(self):
        comment_id = json.loads(self._create_comment(self.reader).content)['id']
        response = Client().put(
            self._comment_url(comment_id),
            data=json.dumps({'content_json': LEXICAL_JSON}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    # ── Delete ────────────────────────────────────────────────────────────

    def test_owner_can_delete_own_comment(self):
        comment_id = json.loads(self._create_comment(self.reader).content)['id']
        response = jwt_client(self.reader).delete(self._comment_url(comment_id))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Comment.objects.get(id=comment_id).is_deleted)

    def test_admin_can_delete_any_comment(self):
        comment_id = json.loads(self._create_comment(self.reader).content)['id']
        response = jwt_client(self.admin).delete(self._comment_url(comment_id))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Comment.objects.get(id=comment_id).is_deleted)

    def test_non_owner_cannot_delete_comment(self):
        comment_id = json.loads(self._create_comment(self.reader).content)['id']
        response = jwt_client(self.other).delete(self._comment_url(comment_id))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Comment.objects.get(id=comment_id).is_deleted)

    def test_unauthenticated_cannot_delete_comment(self):
        comment_id = json.loads(self._create_comment(self.reader).content)['id']
        response = Client().delete(self._comment_url(comment_id))
        self.assertEqual(response.status_code, 401)

    def test_deleted_comment_body_hidden_in_list(self):
        comment_id = json.loads(self._create_comment(self.reader).content)['id']
        jwt_client(self.reader).delete(self._comment_url(comment_id))

        tree = json.loads(Client().get(self._comments_url()).content)
        self.assertTrue(tree[0]['is_deleted'])
        self.assertIsNone(tree[0]['content_json'])
        self.assertIsNone(tree[0]['author'])


# ---------------------------------------------------------------------------
# Blog Utility Function Tests
# ---------------------------------------------------------------------------

class BlogUtilsTests(TestCase):
    """Unit tests for blog/utils.py helpers."""

    def setUp(self):
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        self.other_editor = make_user('other', 'other@example.com', role='editor')
        self.reader = make_user('reader', 'reader@example.com', role='reader')
        self.admin = make_user('admin_user', 'admin@example.com', role='admin')
        self.post = make_post('Test Post', self.editor, slug='test-post')

    def test_create_unique_slug_basic(self):
        slug = create_unique_slug('My Test Title')
        self.assertEqual(slug, 'my-test-title')

    def test_create_unique_slug_avoids_collision(self):
        BlogPost.objects.create(
            title='Collision', slug='collision',
            author=self.editor, content_json=LEXICAL_JSON,
        )
        self.assertEqual(create_unique_slug('Collision'), 'collision-1')

    def test_create_unique_slug_increments_further(self):
        BlogPost.objects.create(title='X', slug='x', author=self.editor, content_json=LEXICAL_JSON)
        BlogPost.objects.create(title='X 1', slug='x-1', author=self.editor, content_json=LEXICAL_JSON)
        self.assertEqual(create_unique_slug('X'), 'x-2')

    def test_can_edit_post_owner(self):
        self.assertTrue(can_edit_post(self.editor, self.post))

    def test_can_edit_post_non_owner_editor(self):
        self.assertFalse(can_edit_post(self.other_editor, self.post))

    def test_can_edit_post_reader(self):
        self.assertFalse(can_edit_post(self.reader, self.post))

    def test_can_edit_post_admin(self):
        self.assertTrue(can_edit_post(self.admin, self.post))

    def test_can_delete_post_owner(self):
        self.assertTrue(can_delete_post(self.editor, self.post))

    def test_can_delete_post_non_owner(self):
        self.assertFalse(can_delete_post(self.other_editor, self.post))

    def test_can_delete_post_reader(self):
        self.assertFalse(can_delete_post(self.reader, self.post))

    def test_can_delete_post_admin(self):
        self.assertTrue(can_delete_post(self.admin, self.post))


# ---------------------------------------------------------------------------
# Blog Model Tests
# ---------------------------------------------------------------------------

class BlogModelTests(TestCase):
    """Unit tests for BlogPost and Category model behavior."""

    def setUp(self):
        self.editor = make_user('editor', 'editor@example.com', role='editor')

    def test_blogpost_auto_slug_on_create(self):
        post = BlogPost.objects.create(
            title='Auto Slug Test', author=self.editor, content_json=LEXICAL_JSON,
        )
        self.assertEqual(post.slug, 'auto-slug-test')

    def test_blogpost_default_status_is_draft(self):
        post = BlogPost.objects.create(
            title='Status Test', slug='status-test',
            author=self.editor, content_json=LEXICAL_JSON,
        )
        self.assertEqual(post.status, 'draft')

    def test_published_at_set_when_status_becomes_published(self):
        post = make_post('To Publish', self.editor, slug='to-publish')
        self.assertIsNone(post.published_at)
        post.status = 'published'
        post.save()
        self.assertIsNotNone(post.published_at)

    def test_published_at_not_overwritten_on_re_save(self):
        post = make_post('Already Published', self.editor, status='published', slug='already-published')
        original_ts = post.published_at
        post.title = 'Updated Title'
        post.save()
        post.refresh_from_db()
        self.assertEqual(post.published_at, original_ts)

    def test_view_count_starts_at_zero(self):
        post = make_post('New Post', self.editor, slug='new-post')
        self.assertEqual(post.view_count, 0)

    def test_increment_view_count(self):
        post = make_post('View Count', self.editor, slug='view-count-post')
        post.increment_view_count()
        self.assertEqual(post.view_count, 1)
        post.increment_view_count()
        self.assertEqual(post.view_count, 2)

    def test_get_content_dict_valid_json(self):
        post = BlogPost(content_json=LEXICAL_JSON)
        content = post.get_content_dict()
        self.assertIsInstance(content, dict)
        self.assertIn('root', content)

    def test_get_content_dict_invalid_json_returns_empty(self):
        post = BlogPost(content_json='not valid json {{')
        self.assertEqual(post.get_content_dict(), {})

    def test_category_m2m_relationship(self):
        cat = Category.objects.create(name='M2M Test', slug='m2m-test')
        post = make_post('M2M Post', self.editor, slug='m2m-post')
        post.categories.add(cat)
        self.assertIn(cat, post.categories.all())
        self.assertIn(post, cat.blog_posts.all())

    def test_blogpost_str(self):
        self.assertEqual(str(BlogPost(title='My Title')), 'My Title')

    def test_category_str(self):
        self.assertEqual(str(Category(name='My Category')), 'My Category')


# ---------------------------------------------------------------------------
# Image Upload Tests (POST /api/blog/upload-image/)
# ---------------------------------------------------------------------------

class ImageUploadTests(TestCase):
    """Tests for POST /api/blog/upload-image/ — blog post image uploads."""

    def setUp(self):
        self.client = Client()
        self.upload_url = '/api/blog/upload-image/'
        self.token_url = '/api/token/pair'
        self.editor = make_user('editor', 'editor@example.com', role='editor')
        self.admin = make_user('admin', 'admin@example.com', role='admin')
        self.reader = make_user('reader', 'reader@example.com', role='reader')
        
        from io import BytesIO
        from PIL import Image
        
        # Create test images
        img = Image.new('RGB', (200, 200), color='blue')
        self.test_jpeg = BytesIO()
        img.save(self.test_jpeg, format='JPEG')
        self.test_jpeg.seek(0)
        self.test_jpeg.name = 'test.jpg'
        
        img_png = Image.new('RGB', (200, 200), color='green')
        self.test_png = BytesIO()
        img_png.save(self.test_png, format='PNG')
        self.test_png.seek(0)
        self.test_png.name = 'test.png'
        
        img_webp = Image.new('RGB', (200, 200), color='red')
        self.test_webp = BytesIO()
        img_webp.save(self.test_webp, format='WebP')
        self.test_webp.seek(0)
        self.test_webp.name = 'test.webp'

    def _get_access_token(self, user):
        response = self.client.post(
            self.token_url,
            data=json.dumps({'username': user.username, 'password': 'ValidPass123'}),
            content_type='application/json'
        )
        return json.loads(response.content)['access']

    def test_upload_image_editor_returns_200(self):
        """Editor can upload images."""
        token = self._get_access_token(self.editor)
        response = self.client.post(
            self.upload_url,
            {'file': self.test_jpeg},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_image_admin_returns_200(self):
        """Admin can upload images."""
        token = self._get_access_token(self.admin)
        response = self.client.post(
            self.upload_url,
            {'file': self.test_jpeg},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_image_reader_returns_403(self):
        """Reader cannot upload images (permission denied)."""
        token = self._get_access_token(self.reader)
        response = self.client.post(
            self.upload_url,
            {'file': self.test_jpeg},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 403)

    def test_upload_image_unauthenticated_returns_401(self):
        """Upload without token returns 401."""
        response = self.client.post(
            self.upload_url,
            {'file': self.test_jpeg}
        )
        self.assertEqual(response.status_code, 401)

    def test_upload_image_returns_url(self):
        """Response includes the image URL."""
        token = self._get_access_token(self.editor)
        response = self.client.post(
            self.upload_url,
            {'file': self.test_jpeg},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        body = json.loads(response.content)
        self.assertIn('url', body)
        self.assertIn('blog_images/', body['url'])

    def test_upload_image_accepts_jpeg(self):
        """JPEG images are accepted."""
        token = self._get_access_token(self.editor)
        response = self.client.post(
            self.upload_url,
            {'file': self.test_jpeg},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_image_accepts_png(self):
        """PNG images are accepted."""
        token = self._get_access_token(self.editor)
        response = self.client.post(
            self.upload_url,
            {'file': self.test_png},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_image_accepts_webp(self):
        """WebP images are accepted."""
        token = self._get_access_token(self.editor)
        response = self.client.post(
            self.upload_url,
            {'file': self.test_webp},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_image_accepts_gif(self):
        """GIF images are accepted."""
        from io import BytesIO
        from PIL import Image
        
        img_gif = Image.new('RGB', (200, 200), color='yellow')
        test_gif = BytesIO()
        img_gif.save(test_gif, format='GIF')
        test_gif.seek(0)
        test_gif.name = 'test.gif'
        
        token = self._get_access_token(self.editor)
        response = self.client.post(
            self.upload_url,
            {'file': test_gif},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_image_rejects_invalid_format(self):
        """Non-image files are rejected."""
        from io import BytesIO
        token = self._get_access_token(self.editor)
        
        invalid_file = BytesIO(b'not an image')
        invalid_file.name = 'fake.txt'
        
        response = self.client.post(
            self.upload_url,
            {'file': invalid_file},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_image_rejects_oversized_image(self):
        """Images over 10 MB are rejected."""
        from io import BytesIO
        from PIL import Image
        
        # Create a large image
        img = Image.new('RGB', (10000, 10000), color='red')
        large_img = BytesIO()
        img.save(large_img, format='JPEG', quality=95)
        large_img.seek(0)
        large_img.name = 'large.jpg'
        
        # Check size
        large_img.seek(0, 2)
        size = large_img.tell()
        large_img.seek(0)
        
        if size > 10 * 1024 * 1024:
            token = self._get_access_token(self.editor)
            response = self.client.post(
                self.upload_url,
                {'file': large_img},
                HTTP_AUTHORIZATION=f'Bearer {token}'
            )
            self.assertEqual(response.status_code, 400)

    def test_upload_image_url_includes_media_url_prefix(self):
        """Returned URL includes the MEDIA_URL prefix."""
        token = self._get_access_token(self.editor)
        response = self.client.post(
            self.upload_url,
            {'file': self.test_jpeg},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        body = json.loads(response.content)
        # Should include /media/ prefix
        self.assertIn('/media/', body['url'])

    def test_upload_image_multiple_uploads_different_urls(self):
        """Multiple image uploads return different URLs."""
        token = self._get_access_token(self.editor)
        
        response1 = self.client.post(
            self.upload_url,
            {'file': self.test_jpeg},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        body1 = json.loads(response1.content)
        url1 = body1['url']
        
        # Reset file pointer
        from io import BytesIO
        from PIL import Image
        img = Image.new('RGB', (200, 200), color='purple')
        img2_file = BytesIO()
        img.save(img2_file, format='JPEG')
        img2_file.seek(0)
        img2_file.name = 'test2.jpg'
        
        response2 = self.client.post(
            self.upload_url,
            {'file': img2_file},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        body2 = json.loads(response2.content)
        url2 = body2['url']
        
        # URLs should be different
        self.assertNotEqual(url1, url2)

    def test_upload_image_missing_file_returns_error(self):
        """POST without file field returns error."""
        token = self._get_access_token(self.editor)
        response = self.client.post(
            self.upload_url,
            {},
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        # Should fail (either 400 or 422)
        self.assertNotEqual(response.status_code, 200)
