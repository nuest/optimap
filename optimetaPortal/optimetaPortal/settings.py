"""
Django settings for geodjango project.

Generated by 'django-admin startproject' using Django 4.0.5.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/
"""

from pathlib import Path
import os
import environ


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# use this if setting up on Windows 10 with GDAL installed from OSGeo4W using defaults
if os.name == 'nt':
    VIRTUAL_ENV_BASE = os.environ['VIRTUAL_ENV']
    os.environ['PATH'] = os.path.join(VIRTUAL_ENV_BASE, r'.\Lib\site-packages\osgeo') + ';' + os.environ['PATH']
    os.environ['PROJ_LIB'] = os.path.join(VIRTUAL_ENV_BASE, r'.\Lib\site-packages\osgeo\data\proj') + ';' + os.environ['PATH']
    GDAL_LIBRARY_PATH = os.path.join(VIRTUAL_ENV_BASE,r'.\Lib\site-packages\osgeo\gdal304.dll')
    GEOS_LIBRARY_PATH = os.path.join(VIRTUAL_ENV_BASE,r'.\Lib\site-packages\osgeo\geos_c.dll')
# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-@(y&etxu!n5qkeyim8ineufd*c*0o20k6$q^$89md-i%qcdk57'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

AUTHENTICATION_BACKENDS = [
    
    'django.contrib.auth.backends.ModelBackend',
    "sesame.backends.ModelBackend",
]
# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    'rest_framework',
    'rest_framework_gis',
    'publications',    
    'django_q',
]

Q_CLUSTER = {
    "name": "optimeta",
    "workers": 1,
    "timeout": 10,
    "retry": 20,
    "queue_limit": 50,
    "bulk": 10,
    "orm": "default",
    "ack_failures": True,
    "max_attempts": 5,
    "attempt_count": 0,
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
# for tetsing only , for production change backend
#EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
#  smtp server settings
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = True



MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.sites.middleware.CurrentSiteMiddleware",
    "sesame.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = 'optimetaPortal.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['publications/static/'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'optimetaPortal.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": "localhost",
        "NAME": "Test1",
        "PASSWORD": "password",
        "PORT": 5432,
        "USER": "mymap",
    }
}

# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = 'publications/static/'

# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

