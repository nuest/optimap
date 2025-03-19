# Generated by Django 5.1.7 on 2025-03-19 14:42

import django.contrib.auth.models
import django.contrib.auth.validators
import django.contrib.gis.db.models.fields
import django.contrib.postgres.fields
import django.db.models.deletion
import django.utils.timezone
import django_currentuser.db.models.fields
import django_currentuser.middleware
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=4096)),
                ('search_term', models.CharField(max_length=4096, null=True)),
                ('timeperiod_startdate', models.DateField(null=True)),
                ('timeperiod_enddate', models.DateField(null=True)),
                ('search_area', django.contrib.gis.db.models.fields.GeometryCollectionField(blank=True, null=True, srid=4326)),
                ('user_name', models.CharField(max_length=4096)),
            ],
            options={
                'verbose_name': 'subscription',
                'ordering': ['user_name'],
            },
        ),
        migrations.CreateModel(
            name='CustomUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('deleted', models.BooleanField(default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('groups', models.ManyToManyField(blank=True, related_name='publications_users', to='auth.group')),
                ('user_permissions', models.ManyToManyField(blank=True, related_name='publications_users_permissions', to='auth.permission')),
            ],
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'abstract': False,
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='BlockedDomain',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(max_length=255, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('blocked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='blocked_domains', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='BlockedEmail',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('blocked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='blocked_emails', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='EmailLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recipient_email', models.EmailField(max_length=254)),
                ('subject', models.CharField(max_length=255)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('email_content', models.TextField(blank=True, null=True)),
                ('trigger_source', models.CharField(choices=[('admin', 'Admin Panel'), ('scheduled', 'Scheduled Task'), ('manual', 'Manually Triggered')], default='manual', max_length=50)),
                ('status', models.CharField(choices=[('d', 'Draft'), ('p', 'Published'), ('t', 'Testing'), ('w', 'Withdrawn'), ('h', 'Harvested')], default='success', max_length=10)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('sent_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Publication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.TextField()),
                ('status', models.CharField(choices=[('d', 'Draft'), ('p', 'Published'), ('t', 'Testing'), ('w', 'Withdrawn'), ('h', 'Harvested')], default='d', max_length=1)),
                ('creationDate', models.DateTimeField(auto_now_add=True)),
                ('lastUpdate', models.DateTimeField(auto_now=True)),
                ('doi', models.CharField(blank=True, max_length=1024, null=True, unique=True)),
                ('source', models.CharField(blank=True, max_length=4096, null=True)),
                ('provenance', models.TextField(blank=True, null=True)),
                ('publicationDate', models.DateField(blank=True, null=True)),
                ('abstract', models.TextField(blank=True, null=True)),
                ('url', models.URLField(blank=True, max_length=1024, null=True)),
                ('geometry', django.contrib.gis.db.models.fields.GeometryCollectionField(blank=True, null=True, srid=4326, verbose_name='Publication geometry/ies')),
                ('timeperiod_startdate', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=1024, null=True), blank=True, null=True, size=None)),
                ('timeperiod_enddate', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=1024, null=True), blank=True, null=True, size=None)),
                ('created_by', django_currentuser.db.models.fields.CurrentUserField(default=django_currentuser.middleware.get_current_authenticated_user, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_creator', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('updated_by', django_currentuser.db.models.fields.CurrentUserField(default=django_currentuser.middleware.get_current_authenticated_user, null=True, on_delete=django.db.models.deletion.CASCADE, on_update=True, related_name='%(app_label)s_%(class)s_updater', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
        migrations.CreateModel(
            name='Source',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('creationDate', models.DateTimeField(auto_now_add=True)),
                ('lastUpdate', models.DateTimeField(auto_now=True)),
                ('url_field', models.URLField(max_length=999)),
                ('harvest_interval_minutes', models.IntegerField(default=4320)),
                ('last_harvest', models.DateTimeField(auto_now_add=True, null=True)),
                ('created_by', django_currentuser.db.models.fields.CurrentUserField(default=django_currentuser.middleware.get_current_authenticated_user, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s_creator', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('updated_by', django_currentuser.db.models.fields.CurrentUserField(default=django_currentuser.middleware.get_current_authenticated_user, null=True, on_delete=django.db.models.deletion.CASCADE, on_update=True, related_name='%(app_label)s_%(class)s_updater', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
        ),
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notify_new_manuscripts', models.BooleanField(default=False)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
