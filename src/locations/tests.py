"""
Tests for the locations app.

Covers models, CRUD endpoints, permission enforcement, geocoding (with the
Google API mocked), picture upload validation, and location comments.

Auth note: protected endpoints use SuspendAwareJWTAuth; tests obtain a real JWT
via POST /api/token/pair and pass it as a Bearer token. Unauthenticated -> 401,
authenticated-but-unauthorised -> 403.
"""
from decimal import Decimal
from io import BytesIO
import json
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings

from blog.models import Comment
from locations.models import Location, RestaurantLocation
from locations.services import LocationService, GeocodingError


LEXICAL_JSON = json.dumps({
    "root": {
        "children": [{
            "children": [{"detail": 0, "format": 0, "mode": "normal",
                          "style": "", "text": "Nice place", "type": "text",
                          "version": 1}],
            "direction": "ltr", "format": "", "indent": 0,
            "type": "paragraph", "version": 1,
        }],
        "direction": "ltr", "format": "", "indent": 0,
        "type": "root", "version": 1,
    }
})


def make_user(username, role='reader'):
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password='ValidPass123'
    )
    user.profile.role = role
    user.profile.email_verified = True
    user.profile.save()
    return user


def auth_headers(client, username, password='ValidPass123'):
    resp = client.post(
        '/api/token/pair',
        data=json.dumps({'username': username, 'password': password}),
        content_type='application/json',
    )
    token = resp.json()['access']
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


def _png_file(name='pic.png', color='blue'):
    from PIL import Image
    buf = BytesIO()
    Image.new('RGB', (40, 40), color=color).save(buf, format='PNG')
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type='image/png')


def make_restaurant(name='Uchi', rating='one_star', published=True, **kwargs):
    location = Location.objects.create(
        type='restaurant',
        name=name,
        address='801 S Lamar Blvd, Austin, TX',
        latitude=Decimal('30.264000'),
        longitude=Decimal('-97.757000'),
        is_published=published,
    )
    RestaurantLocation.objects.create(
        location=location, michelin_rating=rating, cuisine_type='Japanese'
    )
    return location


RESTAURANT_PAYLOAD = {
    'name': 'Franklin Barbecue',
    'description': 'Famous BBQ',
    'address': '900 E 11th St, Austin, TX',
    'phone': '512-555-0100',
    'website': 'https://franklinbbq.com',
    'latitude': '30.270000',
    'longitude': '-97.731000',
    'is_published': True,
    'michelin_rating': 'bib_gourmand',
    'cuisine_type': 'BBQ',
    'reservations_link': 'https://franklinbbq.com/reserve',
    'review_link': 'https://example.com/blog/franklin',
}


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class LocationModelTests(TestCase):
    def test_create_location_defaults(self):
        loc = Location.objects.create(
            type='attraction', name='Zilker Park', address='Austin, TX',
            latitude=Decimal('30.266900'), longitude=Decimal('-97.772800'),
        )
        self.assertTrue(loc.is_published)
        self.assertEqual(loc.description, '')
        self.assertIsNone(loc.created_by)

    def test_location_str(self):
        loc = make_restaurant()
        self.assertIn('Uchi', str(loc))

    def test_restaurant_str_includes_rating_label(self):
        loc = make_restaurant(rating='two_star')
        self.assertIn('Two Stars', str(loc.restaurant))

    def test_restaurant_default_rating_none(self):
        loc = Location.objects.create(
            type='restaurant', name='Plain', address='Austin, TX',
            latitude=Decimal('30.0'), longitude=Decimal('-97.0'),
        )
        RestaurantLocation.objects.create(location=loc)
        self.assertEqual(loc.restaurant.michelin_rating, 'none')


# ---------------------------------------------------------------------------
# Public read
# ---------------------------------------------------------------------------

class LocationListTests(TestCase):
    def setUp(self):
        self.client = Client()
        make_restaurant(name='A')
        make_restaurant(name='B')
        make_restaurant(name='Hidden', published=False)

    def test_list_locations_public(self):
        resp = self.client.get('/api/locations/')
        self.assertEqual(resp.status_code, 200)

    def test_list_excludes_unpublished(self):
        resp = self.client.get('/api/locations/')
        names = [x['name'] for x in resp.json()]
        self.assertNotIn('Hidden', names)
        self.assertEqual(len(names), 2)

    def test_list_filter_by_type(self):
        resp = self.client.get('/api/locations/?type=restaurant')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_list_restaurants_public(self):
        resp = self.client.get('/api/restaurants/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_restaurant_response_has_michelin_and_picture_url(self):
        resp = self.client.get('/api/restaurants/')
        item = resp.json()[0]
        self.assertIn('michelin_rating', item)
        self.assertIn('picture_url', item)
        self.assertIn('cuisine_type', item)

    def test_filter_by_rating(self):
        make_restaurant(name='TwoStar', rating='two_star')
        resp = self.client.get('/api/restaurants/?rating=two_star')
        names = [x['name'] for x in resp.json()]
        self.assertEqual(names, ['TwoStar'])

    def test_filter_by_cuisine(self):
        resp = self.client.get('/api/restaurants/?cuisine=japa')
        self.assertEqual(len(resp.json()), 2)

    def test_search_by_name(self):
        resp = self.client.get('/api/restaurants/?search=a')
        names = [x['name'] for x in resp.json()]
        self.assertIn('A', names)
        self.assertNotIn('B', names)

    def test_detail_public(self):
        loc = Location.objects.get(name='A')
        resp = self.client.get(f'/api/restaurants/{loc.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'A')

    def test_detail_404_for_missing(self):
        resp = self.client.get('/api/restaurants/999999/')
        self.assertEqual(resp.status_code, 404)


class ManageListTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor1', role='editor')
        self.reader = make_user('reader1', role='reader')
        make_restaurant(name='Pub')
        make_restaurant(name='Draft', published=False)

    def test_manage_requires_auth(self):
        resp = self.client.get('/api/locations/manage/')
        self.assertEqual(resp.status_code, 401)

    def test_manage_forbidden_for_reader(self):
        headers = auth_headers(self.client, 'reader1')
        resp = self.client.get('/api/locations/manage/', **headers)
        self.assertEqual(resp.status_code, 403)

    def test_manage_includes_unpublished(self):
        headers = auth_headers(self.client, 'editor1')
        names = [x['name'] for x in self.client.get('/api/locations/manage/', **headers).json()]
        self.assertIn('Draft', names)
        self.assertIn('Pub', names)


# ---------------------------------------------------------------------------
# Create / permission enforcement
# ---------------------------------------------------------------------------

class RestaurantWritePermissionTests(TestCase):
    def setUp(self):
        self.reader = make_user('reader1', role='reader')
        self.editor = make_user('editor1', role='editor')
        self.admin = make_user('admin1', role='admin')

    def test_create_requires_authentication(self):
        resp = self.client.post(
            '/api/restaurants/', data=json.dumps(RESTAURANT_PAYLOAD),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_forbidden_for_reader(self):
        headers = auth_headers(self.client, 'reader1')
        resp = self.client.post(
            '/api/restaurants/', data=json.dumps(RESTAURANT_PAYLOAD),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_allowed_for_editor(self):
        headers = auth_headers(self.client, 'editor1')
        resp = self.client.post(
            '/api/restaurants/', data=json.dumps(RESTAURANT_PAYLOAD),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['name'], 'Franklin Barbecue')
        self.assertEqual(body['michelin_rating'], 'bib_gourmand')
        self.assertTrue(Location.objects.filter(name='Franklin Barbecue').exists())
        self.assertTrue(RestaurantLocation.objects.filter(location_id=body['id']).exists())

    def test_create_sets_created_by(self):
        headers = auth_headers(self.client, 'editor1')
        resp = self.client.post(
            '/api/restaurants/', data=json.dumps(RESTAURANT_PAYLOAD),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.json()['created_by']['username'], 'editor1')

    def test_create_requires_lat_lon(self):
        headers = auth_headers(self.client, 'editor1')
        payload = dict(RESTAURANT_PAYLOAD)
        payload.pop('latitude')
        payload.pop('longitude')
        resp = self.client.post(
            '/api/restaurants/', data=json.dumps(payload),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 422)

    def test_create_forbidden_for_reader_on_locations(self):
        headers = auth_headers(self.client, 'reader1')
        resp = self.client.post(
            '/api/locations/', data=json.dumps({'type': 'attraction', 'name': 'X',
                                                'address': 'Austin', 'latitude': '30.0', 'longitude': '-97.0'}),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_generic_location_create_allowed_for_editor(self):
        headers = auth_headers(self.client, 'editor1')
        resp = self.client.post(
            '/api/locations/',
            data=json.dumps({'type': 'attraction', 'name': 'X', 'address': 'Austin',
                             'latitude': '30.0', 'longitude': '-97.0'}),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['type'], 'attraction')


class RestaurantUpdateDeleteTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor1', role='editor')
        self.admin = make_user('admin1', role='admin')
        self.headers = auth_headers(self.client, 'editor1')
        self.loc = make_restaurant(name='Editable')

    def test_update_requires_auth(self):
        resp = self.client.put(
            f'/api/restaurants/{self.loc.id}/', data=json.dumps({'name': 'New'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_update_partial(self):
        resp = self.client.put(
            f'/api/restaurants/{self.loc.id}/',
            data=json.dumps({'name': 'Renamed', 'michelin_rating': 'three_star'}),
            content_type='application/json', **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['name'], 'Renamed')
        self.assertEqual(body['michelin_rating'], 'three_star')
        # untouched fields preserved
        self.assertEqual(body['cuisine_type'], 'Japanese')

    def test_delete_removes_location_and_detail(self):
        resp = self.client.delete(f'/api/restaurants/{self.loc.id}/', **self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Location.objects.filter(id=self.loc.id).exists())
        self.assertFalse(RestaurantLocation.objects.filter(location_id=self.loc.id).exists())


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

GEOCODE_OK = {
    'status': 'OK',
    'results': [{'geometry': {'location': {'lat': 30.2672, 'lng': -97.7431}}}],
}


@override_settings(GOOGLE_MAPS_API_KEY='test-key')
class GeocodingServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_geocode_success(self):
        with patch('locations.services.urlrequest.urlopen') as mock:
            mock.return_value.__enter__.return_value.read.return_value = json.dumps(GEOCODE_OK).encode()
            lat, lng = LocationService.geocode_address('Austin, TX')
        self.assertEqual(lat, Decimal('30.267200'))
        self.assertEqual(lng, Decimal('-97.743100'))

    def test_geocode_uses_cache(self):
        with patch('locations.services.urlrequest.urlopen') as mock:
            mock.return_value.__enter__.return_value.read.return_value = json.dumps(GEOCODE_OK).encode()
            LocationService.geocode_address('Austin, TX')
            LocationService.geocode_address('Austin, TX')
            self.assertEqual(mock.call_count, 1)

    def test_geocode_empty_address_raises(self):
        with self.assertRaises(GeocodingError):
            LocationService.geocode_address('   ')

    def test_geocode_no_results_raises(self):
        with patch('locations.services.urlrequest.urlopen') as mock:
            mock.return_value.__enter__.return_value.read.return_value = json.dumps(
                {'status': 'ZERO_RESULTS', 'results': []}
            ).encode()
            with self.assertRaises(GeocodingError):
                LocationService.geocode_address('Nowhere')

    def test_geocode_missing_key_raises(self):
        with override_settings(GOOGLE_MAPS_API_KEY=''):
            with self.assertRaises(GeocodingError):
                LocationService.geocode_address('Austin, TX')


@override_settings(GOOGLE_MAPS_API_KEY='test-key')
class GeocodeEndpointTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor1', role='editor')
        self.reader = make_user('reader1', role='reader')
        cache.clear()

    def test_geocode_requires_auth(self):
        resp = self.client.post(
            '/api/locations/geocode/', data=json.dumps({'address': 'Austin, TX'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_geocode_forbidden_for_reader(self):
        headers = auth_headers(self.client, 'reader1')
        resp = self.client.post(
            '/api/locations/geocode/', data=json.dumps({'address': 'Austin, TX'}),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_geocode_success(self):
        headers = auth_headers(self.client, 'editor1')
        with patch('locations.services.urlrequest.urlopen') as mock:
            mock.return_value.__enter__.return_value.read.return_value = json.dumps(GEOCODE_OK).encode()
            resp = self.client.post(
                '/api/locations/geocode/', data=json.dumps({'address': 'Austin, TX'}),
                content_type='application/json', **headers,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(resp.json()['latitude']), Decimal('30.267200'))

    def test_geocode_error_returns_400(self):
        headers = auth_headers(self.client, 'editor1')
        with patch('locations.services.urlrequest.urlopen') as mock:
            mock.return_value.__enter__.return_value.read.return_value = json.dumps(
                {'status': 'ZERO_RESULTS', 'results': []}
            ).encode()
            resp = self.client.post(
                '/api/locations/geocode/', data=json.dumps({'address': 'Nowhere'}),
                content_type='application/json', **headers,
            )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Picture upload
# ---------------------------------------------------------------------------

class PictureUploadTests(TestCase):
    def setUp(self):
        self._media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self._media)
        self.override.enable()
        self.editor = make_user('editor1', role='editor')
        self.headers = auth_headers(self.client, 'editor1')
        self.loc = make_restaurant(name='PicTest')

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self._media, ignore_errors=True)

    def test_upload_requires_auth(self):
        resp = self.client.post(
            f'/api/locations/{self.loc.id}/picture/', data={'file': _png_file()}
        )
        self.assertEqual(resp.status_code, 401)

    def test_upload_rejects_bad_content_type(self):
        bad = SimpleUploadedFile('x.txt', b'hello', content_type='text/plain')
        resp = self.client.post(
            f'/api/locations/{self.loc.id}/picture/', data={'file': bad}, **self.headers
        )
        self.assertEqual(resp.status_code, 400)

    def test_upload_success_sets_picture(self):
        resp = self.client.post(
            f'/api/locations/{self.loc.id}/picture/', data={'file': _png_file()}, **self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.loc.refresh_from_db()
        self.assertTrue(self.loc.picture)
        self.assertIn('picture_url', resp.json())


# ---------------------------------------------------------------------------
# Location comments
# ---------------------------------------------------------------------------

class LocationCommentTests(TestCase):
    def setUp(self):
        self.reader = make_user('reader1', role='reader')
        self.other = make_user('other1', role='reader')
        self.admin = make_user('admin1', role='admin')
        self.loc = make_restaurant(name='Commentable')

    def test_list_comments_public_empty(self):
        resp = self.client.get(f'/api/locations/{self.loc.id}/comments/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_create_comment_requires_auth(self):
        resp = self.client.post(
            f'/api/locations/{self.loc.id}/comments/',
            data=json.dumps({'content_json': LEXICAL_JSON}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_and_list_comment(self):
        headers = auth_headers(self.client, 'reader1')
        resp = self.client.post(
            f'/api/locations/{self.loc.id}/comments/',
            data=json.dumps({'content_json': LEXICAL_JSON}),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 200)
        listing = self.client.get(f'/api/locations/{self.loc.id}/comments/').json()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]['author']['username'], 'reader1')

    def test_comment_isolated_to_location(self):
        """A location comment must not leak into blog/recipe comment trees."""
        Comment.objects.create(location=self.loc, author=self.reader, content_json=LEXICAL_JSON)
        self.assertEqual(Comment.objects.filter(location=self.loc).count(), 1)
        self.assertEqual(Comment.objects.filter(post__isnull=False).count(), 0)

    def test_edit_own_comment(self):
        headers = auth_headers(self.client, 'reader1')
        comment = Comment.objects.create(location=self.loc, author=self.reader, content_json=LEXICAL_JSON)
        resp = self.client.put(
            f'/api/locations/comments/{comment.id}/',
            data=json.dumps({'content_json': LEXICAL_JSON}),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 200)

    def test_edit_others_comment_forbidden(self):
        comment = Comment.objects.create(location=self.loc, author=self.reader, content_json=LEXICAL_JSON)
        headers = auth_headers(self.client, 'other1')
        resp = self.client.put(
            f'/api/locations/comments/{comment.id}/',
            data=json.dumps({'content_json': LEXICAL_JSON}),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_own_comment_soft_deletes(self):
        headers = auth_headers(self.client, 'reader1')
        comment = Comment.objects.create(location=self.loc, author=self.reader, content_json=LEXICAL_JSON)
        resp = self.client.delete(f'/api/locations/comments/{comment.id}/', **headers)
        self.assertEqual(resp.status_code, 200)
        comment.refresh_from_db()
        self.assertTrue(comment.is_deleted)

    def test_admin_can_delete_others_comment(self):
        comment = Comment.objects.create(location=self.loc, author=self.reader, content_json=LEXICAL_JSON)
        headers = auth_headers(self.client, 'admin1')
        resp = self.client.delete(f'/api/locations/comments/{comment.id}/', **headers)
        self.assertEqual(resp.status_code, 200)

    def test_comments_only_on_published_location(self):
        hidden = make_restaurant(name='Hidden', published=False)
        resp = self.client.get(f'/api/locations/{hidden.id}/comments/')
        self.assertEqual(resp.status_code, 404)
