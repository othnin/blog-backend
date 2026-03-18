# Blog App Implementation Guide

## Overview

The blog app has been created as a Django application with full support for blog post creation, editing, and publishing using Lexical editor format for content storage.

## Database Schema

### Models Created

#### 1. **UserProfile** (Updated)
Extended user profile with two new fields:
- `avatar` (URLField, optional): URL to user's avatar image
- `role` (CharField): User's blog role with three options:
  - `reader`: Read-only access (cannot create/edit posts)
  - `editor`: Can create and edit own posts (cannot publish by default)
  - `admin`: Full access to all posts

**Fields:**
```python
- user (OneToOneField → User)
- email_verified (Boolean)
- avatar (URLField)
- role (CharField: 'reader', 'editor', 'admin')
- created_at (DateTime)
- updated_at (DateTime)
```

#### 2. **Category**
Blog post categories for organizing content.

**Fields:**
```python
- id (BigAutoField, PK)
- name (CharField, unique, indexed)
- slug (SlugField, unique, indexed)
- created_at (DateTime)
- updated_at (DateTime)
```

#### 3. **BlogPost**
Main blog post model supporting Lexical editor format.

**Fields:**
```python
- id (BigAutoField, PK)
- title (CharField, max_length=500, indexed)
- slug (SlugField, unique, indexed)
- author (ForeignKey → User, related_name='blog_posts')
- content_json (TextField) - Lexical editor JSON format
- featured_image_url (URLField, optional)
- categories (ManyToManyField → Category)
- status (CharField: 'draft', 'published', 'scheduled', 'archived')
- published_at (DateTime, indexed, auto-set when published)
- view_count (PositiveIntegerField, default=0)
- created_at (DateTime, indexed)
- updated_at (DateTime)
```

**Database Relations:**
- `blog_blogpost`: Main posts table
- `blog_blogpost_categories`: M2M junction table for categories
- `auth_app_userprofile`: Extended user profiles

## File Structure

```
backend/src/blog/
├── __init__.py
├── admin.py              # Django admin configuration
├── apps.py               # App configuration
├── models.py             # BlogPost, Category models
├── serializers.py        # Pydantic serializers for API
├── utils.py              # Helper functions (permissions, queries)
├── api.py                # Django Ninja API endpoints
├── tests.py              # Test suite (placeholder)
└── migrations/
    ├── __init__.py
    ├── 0001_initial.py   # Initial schema creation
    └── __pycache__/
```

## API Endpoints

All endpoints are available at `/api/blog/`.

### Categories

**GET `/api/blog/categories/`**
- Get all blog categories
- No authentication required
- Returns: List of categories

### Blog Posts

**GET `/api/blog/posts/`**
- Get published blog posts
- No authentication required
- Query params: `limit` (optional)
- Returns: List of published posts (summary format)

**GET `/api/blog/posts/{slug}/`**
- Get a single published blog post by slug
- No authentication required
- Automatically increments view count
- Returns: Full blog post details

**POST `/api/blog/posts/`**
- Create a new blog post
- Requires: Authenticated user with 'editor' or 'admin' role
- Body: `BlogPostCreateIn` (title, content_json, featured_image_url, category_ids, status)
- Returns: Created blog post details
- Auto-sets author to current user
- Auto-generates unique slug
- Auto-sets published_at when status='published'

**PUT `/api/blog/posts/{post_id}/`**
- Update a blog post
- Requires: Authentication + permission (own post for editor, any for admin)
- Body: `BlogPostUpdateIn` (all fields optional)
- Returns: Updated blog post details

**DELETE `/api/blog/posts/{post_id}/`**
- Delete a blog post
- Requires: Authentication + permission (own post for editor, any for admin)
- Returns: Success message

**GET `/api/blog/my-posts/`**
- Get current user's blog posts (including drafts)
- Requires: Authenticated user
- Returns: List of user's posts

## Permission Model

### Editor Role
- ✓ Create blog posts (status can be 'draft' or 'published')
- ✓ Edit only their own posts
- ✓ Delete only their own posts
- ✓ View all published posts
- ✓ View their own drafts

### Admin Role
- ✓ Create blog posts
- ✓ Edit any blog post
- ✓ Delete any blog post
- ✓ View all posts (published and drafts)
- ✓ Manage categories
- ✓ Approve/archive any post

### Reader Role
- ✓ View published posts
- ✗ Create posts
- ✗ Edit posts
- ✗ Delete posts

## Content Storage: Lexical Format

Blog content is stored as JSON in Lexical editor format. Example structure:

```json
{
  "root": {
    "children": [
      {
        "children": [
          {
            "detail": 0,
            "format": 0,
            "mode": "normal",
            "style": "",
            "text": "Your blog content here",
            "type": "text",
            "version": 1
          }
        ],
        "direction": "ltr",
        "format": "",
        "indent": 0,
        "type": "paragraph",
        "version": 1
      }
    ],
    "direction": "ltr",
    "format": "",
    "indent": 0,
    "type": "root",
    "version": 1
  }
}
```

The JSON is validated on API input and can be rendered directly by Lexical on the frontend.

## Usage Examples

### Create a Blog Post (as Editor)

```bash
curl -X POST http://localhost:8000/api/blog/posts/ \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My First Blog Post",
    "content_json": "{\"root\":{\"children\":[{\"children\":[{\"text\":\"Hello World\",\"type\":\"text\"}],\"type\":\"paragraph\"}],\"type\":\"root\"}}",
    "featured_image_url": "https://example.com/image.jpg",
    "category_ids": [1, 2],
    "status": "draft"
  }'
```

### Publish a Draft Post

```bash
curl -X PUT http://localhost:8000/api/blog/posts/1/ \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "published"
  }'
```

### Get Published Posts

```bash
curl http://localhost:8000/api/blog/posts/
```

## Utility Functions

See [blog/utils.py](utils.py) for helper functions:

- `create_unique_slug(title, existing_slugs)`: Generate unique URL-friendly slugs
- `can_edit_post(user, blog_post)`: Check edit permissions
- `can_publish_post(user, blog_post)`: Check publish permissions
- `can_delete_post(user, blog_post)`: Check delete permissions
- `get_published_posts(limit)`: Retrieve published posts
- `get_user_posts(user, include_drafts)`: Get user's posts

## Admin Interface

Django admin interface is configured for managing blog content:

**Categories:**
- View, create, edit categories
- Slug auto-generation from name
- Search by name

**Blog Posts:**
- View, create, edit, delete posts
- Filter by status and date
- Search by title, slug, author
- Manage categories (M2M)
- View analytics (view count)
- Read-only fields: view_count, timestamps

## Next Steps

### Frontend Implementation
1. Create blog list page at `/blog/posts/`
2. Create blog detail page at `/blog/[slug]/`
3. Create blog editor page at `/dashboard/create-post/`
4. Integrate Lexical editor library for content creation
5. Display featured images and categories

### Upcoming Features (Phase 2)
- [ ] Comments system
- [ ] Blog post search/filtering
- [ ] Tags in addition to categories
- [ ] Blog post scheduling (published_at scheduling)
- [ ] SEO metadata fields (meta description, keywords)
- [ ] Draft auto-save
- [ ] Post revision history
- [ ] Blog analytics dashboard

## Testing

Run tests with:
```bash
python manage.py test blog
```

## Settings Configuration

The blog app is registered in `home/settings.py`:

```python
INSTALLED_APPS = [
    ...
    "blog",
    ...
]
```

Database configuration supports both SQLite (development) and PostgreSQL (production) via `DATABASE_URL` environment variable.
