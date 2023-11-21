"""
Django settings for geodjango project.

Generated by 'django-admin startproject' using Django 4.0.5.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/

See also
https://djangocentral.com/environment-variables-in-django/
"""

import os
import environ
import dj_database_url
import re

# .env file in the same directory as settings.py
env = environ.Env()
environ.Env.read_env()

# use this if setting up on Windows 10 with GDAL installed from OSGeo4W using defaults
if os.name == 'nt':
    VIRTUAL_ENV_BASE = os.environ['VIRTUAL_ENV']
    os.environ['PATH'] = os.path.join(VIRTUAL_ENV_BASE, r'.\Lib\site-packages\osgeo') + ';' + os.environ['PATH']
    os.environ['PROJ_LIB'] = os.path.join(VIRTUAL_ENV_BASE, r'.\Lib\site-packages\osgeo\data\proj') + ';' + os.environ['PATH']
    GDAL_LIBRARY_PATH = os.path.join(VIRTUAL_ENV_BASE,r'.\Lib\site-packages\osgeo\gdal304.dll')
    GEOS_LIBRARY_PATH = os.path.join(VIRTUAL_ENV_BASE,r'.\Lib\site-packages\osgeo\geos_c.dll')


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('OPTIMAP_DEBUG', default=True)

ALLOWED_HOSTS = [i.strip('[]') for i in env('OPTIMAP_ALLOWED_HOST', default='*').split(',')]

OPTIMAP_SUPERUSER_EMAILS = [i.strip('[]') for i in env('OPTIMAP_SUPERUSER_EMAILS', default='').split(',')]

TEST_HARVESTING_ONLINE = env('OPTIMAP_TEST_HARVESTING_ONLINE', default=False)

ROOT_URLCONF = 'optimap.urls'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    "sesame.backends.ModelBackend",
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    'django.contrib.sitemaps',
    'rest_framework',
    'rest_framework_gis',
    'publications',
    'django_q',
    'drf_spectacular',
    'drf_spectacular_sidecar',
    'leaflet',
    'import_export',
]

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
	'PAGE_SIZE': 999,
}

# https://github.com/tfranzel/drf-spectacular
SPECTACULAR_SETTINGS = {
    'TITLE': 'OPTIMAP API',
    'DESCRIPTION': 'OPTIMAP provides geospatial metadata for scientific publications.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_DIST': 'SIDECAR',  # shorthand to use the sidecar instead
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
    # https://github.com/Redocly/redoc#redoc-options-object
    'REDOC_UI_SETTINGS': {
        # https://github.com/Redocly/redoc#redoc-theme-object
        'theme': {
            'sidebar': {
                # 'backgroundColor': '#ff0000',
            },
            'colors': {
                'primary': {
                    'main': '#158F9B',
                    'light': '#B9F0F6'
                },
                "http": {
                    "get": "#158F9B",
                    "post": "#3C159B",
                    "put": "#3C159B",
                    "delete": "#9B2115"
                },
                "success": {
                    "main": "#158F9B",
                    "light": "#9B7115",
                    "dark": "#3C159B",
                    "contrastText": "#000"
                },
                "text": {
                    "primary": "rgba(0, 0, 0, 1)",
                    "secondary": "#158F9B"
                },
            },
            "typography": {
                "heading1": {
                    "color": "#158F9B",
                },
                "heading2": {
                    "color": "#158F9B",
                },
                "heading3": {
                    "color": "#158F9B",
                },
                "links": {
                    "color": "#158F9B",
                    "visited": "#158F9B",
                    "hover": "#3C159B"
                }
            },
        }
    },
}

Q_CLUSTER = {
    'name': 'optimap',
    'workers': 1,
    'timeout': 10,
    'retry': 20,
    'queue_limit': 50,
    'bulk': 10,
    'orm': 'default',
    'ack_failures': True,
    'max_attempts': 5,
    'attempt_count': 0,
}

CACHES = {
    # defaults to database caching to persist across processes, see https://docs.djangoproject.com/en/4.1/topics/cache/#local-memory-caching
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'cache',
    },

    # use for development
    'dummy': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    },

    #'redis': {
    #    "BACKEND": "django_redis.cache.RedisCache",
    #    "LOCATION": "redis://127.0.0.1:6379/1",
    #    "OPTIONS": {
    #        "CLIENT_CLASS": "django_redis.client.DefaultClient",
    #    },
    #}
}

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db" # store session data in database, it's persistent and fast enough for us

CACHE_MIDDLEWARE_ALIAS = env('OPTIMAP_CACHE', default='default')
CACHE_MIDDLEWARE_SECONDS = env('OPTIMAP_CACHE_SECONDS', default=3600)

# for testing email sending EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_BACKEND =       env('OPTIMAP_EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST =          env('OPTIMAP_EMAIL_HOST', default='optimap.dev')
EMAIL_PORT =          env('OPTIMAP_EMAIL_PORT_SMTP', default=587)
EMAIL_HOST_IMAP =     env('OPTIMAP_EMAIL_HOST_IMAP', default='optimap.imap')
EMAIL_PORT_IMAP =     env('OPTIMAP_EMAIL_PORT_IMAP', default=993)
EMAIL_HOST_USER =     env('OPTIMAP_EMAIL_HOST_USER', default='optimap@dev')
EMAIL_HOST_PASSWORD = env('OPTIMAP_EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS =       env('OPTIMAP_EMAIL_USE_TLS', default=False)
EMAIL_USE_SSL =       env('OPTIMAP_EMAIL_USE_SSL', default=False)
EMAIL_IMAP_SENT_FOLDER = env('OPTIMAP_EMAIL_IMAP_SENT_FOLDER', default='')

MIDDLEWARE = [
    'django.middleware.cache.UpdateCacheMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.cache.FetchFromCacheMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.cache.UpdateCacheMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.cache.FetchFromCacheMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.sites.middleware.CurrentSiteMiddleware",
    "sesame.middleware.AuthenticationMiddleware",
    "django_currentuser.middleware.ThreadLocalUserMiddleware",
]

ROOT_URLCONF = 'optimap.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['publications/templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'optimap.urls.site',
            ],
        },
    },
]

WSGI_APPLICATION = 'optimap.wsgi.application'

# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases
# https://pypi.org/project/dj-database-url/
DATABASES = {
    'default': dj_database_url.config( # this uses DATABASE_URL environment variable
        # value must be URL-encoded: postgres://user:p%23ssword!@localhost/foobar
        default='postgis://optimap:optimap@localhost:5432/optimap',
        conn_max_age=600
        )
}

# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/
# https://docs.djangoproject.com/en/4.1/ref/contrib/staticfiles/
STATIC_ROOT = 'static/'
STATIC_URL = '/static/'
STATICFILES_DIRS = ['publications/static']

# serve static files with Django, not with a dedicated webserver: http://whitenoise.evans.io/en/stable/django.html
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        'require_debug_true': { # passes on records when DEBUG is True
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        },
        'mail_admins': {
            'level': 'WARNING',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
            'include_html': True
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'mail_admins'],
            'level': 'INFO',
        },
        'publications': {
            'handlers': ['console', 'mail_admins'],
            'level': env('OPTIMAP_LOGGING_CONSOLE_LEVEL', default='INFO'),
        },
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'WARNING',
            'propagate': False,
        }
    }
}

IGNORABLE_404_URLS = (
    re.compile(r"\.(php|cgi|env)$"),
    re.compile(r"^/phpmyadmin/"),
    re.compile(r'wp-login$'),
    re.compile(r'(.*)/wp-includes/(.*)'),
    re.compile(r"^/(http|https)$"),
    re.compile(r"ads.txt$"),
    re.compile(r"^\.git"),
)

CSRF_TRUSTED_ORIGINS = [i.strip('[]') for i in env('CSRF_TRUSTED_ORIGINS', default='https://localhost:8000').split(',')]

ADMINS = [('OPTIMAP', 'login@optimap.science')]
