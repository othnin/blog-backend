from django.db import migrations, models


def backfill_content_text(apps, schema_editor):
    """Populate content_text for all existing blog posts."""
    from blog.models import _lexical_to_text
    BlogPost = apps.get_model('blog', 'BlogPost')
    posts = BlogPost.objects.exclude(content_json='')
    for post in posts:
        post.content_text = _lexical_to_text(post.content_json)
    BlogPost.objects.bulk_update(posts, ['content_text'])


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0002_comment'),
    ]

    operations = [
        migrations.AddField(
            model_name='blogpost',
            name='content_text',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Plain-text extract of content_json, kept in sync on save, used for full-text search',
            ),
        ),
        migrations.RunPython(backfill_content_text, migrations.RunPython.noop),
    ]
