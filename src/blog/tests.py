"""
Unit tests for blog endpoints, models, and utilities.

Authentication note: the blog controller uses ninja_extra permissions=[IsAuthenticated]
without an explicit auth=JWTAuth() scheme, so request.user is populated via Django's
session middleware.  Tests authenticate with force_login().  Unauthenticated requests
return 403 (ninja_extra IsAuthenticated permission denial), not 401.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
import json

from blog.models import BlogPost, Category
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


def logged_in_client(user):
    """Return a Django test client authenticated as *user* via session."""
    c = Client()
    c.force_login(user)
    return c


# ---------------------------------------------------------------------------
# Category Tests
# ---------------------------------------------------------------------------

class CategoryTests(TestCase):
    """Tests for GET /api/blog/categories/"""

    def setUp(self):
        self.client = Client()
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
        # Draft posts are not accessible by slug (status='published' filter)
        response = self.client.get('/api/blog/posts/draft-post/')
        self.assertEqual(response.status_code, 404)

    def test_response_includes_content_and_author(self):
        response = self.client.get('/api/blog/posts/published-post/')
        data = json.loads(response.content)
        self.assertIn('content_json', data)
        self.assertIn('author', data)
        self.assertIn('view_count', data)


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
        client = logged_in_client(user) if user else Client()
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
        # IsAuthenticated permission returns 403 for anonymous users
        response = self._post(self.valid_data)
        self.assertEqual(response.status_code, 403)

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
        # Slug must differ from the first post's slug
        self.assertNotEqual(result['slug'], 'my-new-post')

    def test_empty_title_rejected(self):
        data = {'title': '', 'content_json': LEXICAL_JSON}
        response = self._post(data, self.editor)
        self.assertNotEqual(response.status_code, 200)


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
        client = logged_in_client(user) if user else Client()
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
        self.assertEqual(response.status_code, 403)

    def test_publishing_sets_published_at(self):
        response = self._put({'status': 'published'}, self.editor)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(result['status'], 'published')
        self.assertIsNotNone(result['published_at'])

    def test_update_nonexistent_post_returns_error(self):
        response = self._put({'title': 'Ghost'}, self.admin, post_id=99999)
        # May return 404 or 405 depending on route matching; either way not 200
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
        client = logged_in_client(self.editor)
        response = client.delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BlogPost.objects.filter(id=post.id).exists())

    def test_non_owner_cannot_delete_post(self):
        post = self._new_post(self.editor)
        client = logged_in_client(self.other_editor)
        response = client.delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 403)
        self.assertTrue(BlogPost.objects.filter(id=post.id).exists())

    def test_admin_can_delete_any_post(self):
        post = self._new_post(self.editor)
        client = logged_in_client(self.admin)
        response = client.delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BlogPost.objects.filter(id=post.id).exists())

    def test_unauthenticated_cannot_delete_post(self):
        post = self._new_post()
        response = Client().delete(f'/api/blog/posts/{post.id}/')
        self.assertEqual(response.status_code, 403)
        self.assertTrue(BlogPost.objects.filter(id=post.id).exists())

    def test_delete_nonexistent_post_returns_404(self):
        client = logged_in_client(self.admin)
        response = client.delete('/api/blog/posts/99999/')
        self.assertEqual(response.status_code, 404)

    def test_reader_cannot_delete_post(self):
        post = self._new_post(self.editor)
        client = logged_in_client(self.reader)
        response = client.delete(f'/api/blog/posts/{post.id}/')
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
        client = logged_in_client(self.editor)
        response = client.get('/api/blog/my-posts/')
        self.assertEqual(response.status_code, 200)
        titles = {p['title'] for p in json.loads(response.content)}
        self.assertIn('My Draft', titles)
        self.assertIn('My Published', titles)
        self.assertNotIn('Others Post', titles)

    def test_includes_drafts(self):
        client = logged_in_client(self.editor)
        response = client.get('/api/blog/my-posts/')
        statuses = {p['status'] for p in json.loads(response.content)}
        self.assertIn('draft', statuses)

    def test_unauthenticated_returns_403(self):
        response = Client().get('/api/blog/my-posts/')
        self.assertEqual(response.status_code, 403)

    def test_each_user_sees_only_their_posts(self):
        client = logged_in_client(self.other)
        response = client.get('/api/blog/my-posts/')
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['title'], 'Others Post')


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
