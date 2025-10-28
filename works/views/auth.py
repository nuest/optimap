"""
Authentication and user account management views.

This module handles:
- Magic link authentication
- User login/logout
- User settings and subscriptions
- Email changes
- Account deletion
"""

import logging
logger = logging.getLogger(__name__)

from django.contrib.auth import login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect
from urllib.parse import unquote
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.core.mail import EmailMessage, get_connection, send_mail
import secrets
import uuid
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.urls import reverse
from datetime import datetime
import imaplib
import time
from math import floor
from django.conf import settings
from works.models import BlockedEmail, BlockedDomain, Subscription, UserProfile, GlobalRegion
from django.contrib.auth import get_user_model

User = get_user_model()

# Constants
LOGIN_TOKEN_LENGTH = 32
LOGIN_TOKEN_TIMEOUT_SECONDS = 10 * 60
EMAIL_CONFIRMATION_TIMEOUT_SECONDS = 10 * 60
ACCOUNT_DELETE_TOKEN_TIMEOUT_SECONDS = 10 * 60
USER_DELETE_TOKEN_PREFIX = "user_delete_token"
EMAIL_CONFIRMATION_TOKEN_PREFIX = "email_confirmation_"


def loginres(request):
    email = request.POST.get('email', False)
    if is_email_blocked(email):
        logger.warning('Attempted login with blocked email: %s', email)
        return render(request, "error.html", {
            'error': {
                'class': 'danger',
                'title': 'Login failed!',
                'text': f"You attempted to login using an email that is blocked. Please contact support for assistance: <a href=\"{request.site.domain}/contact\">{request.site.domain}/contact</a>"
                }
        })
    else:
        subject = 'OPTIMAP Login'
        link = get_login_link(request, email)
        valid = floor(LOGIN_TOKEN_TIMEOUT_SECONDS / 60)
        body = f"""Hello {email} !

You requested that we send you a link to log in to OPTIMAP at {request.site.domain}:

{link}

Please click on the link to log in.
The link is valid for {valid} minutes.
"""
        logger.info('Login process started for user %s', email)
        try:
            email_message = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.EMAIL_HOST_USER,
                to=[email],
                headers={'OPTIMAP': request.site.domain}
            )
            result = email_message.send()
            logger.info('%s sent login email to %s with the result: %s', settings.EMAIL_HOST_USER, email_message.recipients(), result)
        except Exception as ex:
            logger.exception('Error sending login email to %s from %s', email, settings.EMAIL_HOST_USER)
            logger.error(ex)
            return render(request, "error.html", {
                'error': {
                    'class': 'danger',
                    'title': 'Login failed!',
                    'text': 'Error sending the login email. Please try again or contact us!'
                }
            })

        try:
            if str(get_connection().__class__.__module__).endswith("smtp"):
                with imaplib.IMAP4_SSL(settings.EMAIL_HOST_IMAP, port=settings.EMAIL_PORT_IMAP) as imap:
                    message = str(email_message.message()).encode()
                    imap.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
                    folder = settings.EMAIL_IMAP_SENT_FOLDER
                    imap.append('"{folder}"', '\\Seen', imaplib.Time2Internaldate(time.time()), str(message).encode('utf-8'))
                    logger.debug('Saved email to IMAP folder "%s"', folder)
        except Exception as ex:
            logger.exception('Error saving sent email to %s for %s', email, settings.EMAIL_HOST_USER)
            logger.error(ex)

        return render(request, 'login_response.html', {'email': email, 'valid_minutes': valid})

def confirmation_login(request):
    return render(request, 'confirmation_login.html')

def login_user(request, user):
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    user.save()

@require_GET

def authenticate_via_magic_link(request, token):
    cache_data = cache.get(token)
    logger.info('Authenticating magic link with token %s: Found data: %s', token, cache_data)

    if cache_data is None:
        logger.debug('Magic link invalid or expired')
        return render(request, "error.html", {
            'error': {
                'class': 'danger',
                'title': 'Authentication failed!',
                'text': 'Magic link invalid or expired. Please try again!'
            }
        })

    # Extract email and next URL from cache data
    email = cache_data.get('email')
    next_url = cache_data.get('next', '/')

    # Ensure next_url is valid - default to home if empty or invalid
    if not next_url or next_url.strip() == '':
        next_url = '/'

    user = User.objects.filter(email=email).first()
    if user:
        is_new = False
        needs_confirmation = False
        login_user(request, user)
        # Store next URL in session for redirect after confirmation
        request.session['login_redirect_url'] = next_url
    elif request.GET.get('confirmed', None) == 'true':
        user = User.objects.create_user(username=email, email=email)
        is_new = True
        needs_confirmation = False
        login_user(request, user)
        # Redirect to next URL after successful login
        logger.info('User %s logged in successfully, redirecting to %s', email, next_url)
        return HttpResponseRedirect(next_url)
    else:
        is_new = True
        needs_confirmation = True
        # Store next URL for redirect after confirmation
        request.session['login_redirect_url'] = next_url

    # If user is already authenticated and doesn't need confirmation, redirect
    if not needs_confirmation and user:
        logger.info('User %s authenticated, redirecting to %s', email, next_url)
        return HttpResponseRedirect(next_url)

    return render(request, "confirmation_login.html", {
        'email': email,
        'token': token,
        'is_new': is_new,
        'needs_confirmation': needs_confirmation,
        'next': next_url
    })

@login_required

def customlogout(request):
    logout(request)
    messages.info(request, "You have successfully logged out.")
    return render(request, "logout.html")

@never_cache

def user_settings(request):
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        profile.notify_new_manuscripts = request.POST.get("notify_new_manuscripts") == "on"
        profile.save()
        return redirect(reverse("optimap:usersettings"))
    return render(request, "user_settings.html", {
        "profile": profile,
        "delete_token": request.session.get(USER_DELETE_TOKEN_PREFIX, None),
    })

@login_required

def user_subscriptions(request):
    """Display and manage user's regional subscriptions."""
    user = request.user

    # Get or create the user's subscription
    subscription, created = Subscription.objects.get_or_create(
        user=user,
        defaults={'name': f'{user.username}_subscription'}
    )

    # Get all available regions, grouped by type
    continents = GlobalRegion.objects.filter(region_type=GlobalRegion.CONTINENT).order_by('name')
    oceans = GlobalRegion.objects.filter(region_type=GlobalRegion.OCEAN).order_by('name')

    # Get user's currently selected regions
    selected_region_ids = list(subscription.regions.values_list('id', flat=True))

    context = {
        'subscription': subscription,
        'continents': continents,
        'oceans': oceans,
        'selected_region_ids': selected_region_ids,
    }

    return render(request, 'subscriptions.html', context)

@login_required

def add_subscriptions(request):
    """Update user's regional subscriptions."""
    if request.method == "POST":
        user = request.user

        # Get or create the user's subscription
        subscription, created = Subscription.objects.get_or_create(
            user=user,
            defaults={'name': f'{user.username}_subscription'}
        )

        # Get selected region IDs from the form
        selected_region_ids = request.POST.getlist('regions')

        # Update the subscription's regions
        subscription.regions.clear()
        if selected_region_ids:
            regions = GlobalRegion.objects.filter(id__in=selected_region_ids)
            subscription.regions.set(regions)

        logger.info('Updated subscription for user %s with %d regions', user.username, len(selected_region_ids))
        messages.success(request, f'Subscription updated! Monitoring {len(selected_region_ids)} regions.')

        return HttpResponseRedirect('/subscriptions/')

    return HttpResponseRedirect('/subscriptions/')

@login_required

def unsubscribe(request):
    """Handles unsubscription requests from emails."""
    user = request.user
    search_term = request.GET.get("search")
    unsubscribe_all = request.GET.get("all")

    if unsubscribe_all:
        Subscription.objects.filter(user=user).update(subscribed=False)
        messages.success(request, "You have been unsubscribed from all subscriptions.")
        return redirect("/")
    if search_term:
        exact_search_term = unquote(search_term).strip()
        subscription = get_object_or_404(Subscription, user=user, search_term=exact_search_term)
        if not subscription:
            messages.warning(request, f"No subscription found for '{search_term}'.")
            return redirect("/")
        subscription.subscribed = False
        subscription.save()
        messages.success(request, f"You have unsubscribed from '{search_term}'.")
        return redirect("/")

    return HttpResponse("Invalid request.", status=400)

def delete_account(request):
    email = request.user.email
    logger.info('Delete account for %s', email)
    User.objects.filter(email=email).delete()
    messages.info(request, 'Your account has been successfully deleted.')
    return render(request, 'deleteaccount.html')

@login_required

def change_useremail(request):
    email_new = request.POST.get('email_new', False)
    currentuser = request.user
    email_old = currentuser.email
    if is_email_blocked(email_new):
        logger.warning('Attempted login with blocked email: %s', email_new)
        return render(request, "error.html", {
            'error': {
                'class': 'danger',
                'title': 'Login failed!',
                'text': 'You attempted to change your email to an address that is blocked. Please contact support for assistance.'
            }
        })
    if not email_new or email_new == email_old:
        messages.error(request, "Invalid email change request.")
        return render(request, "error.html", {
            'error': {
                'class': 'danger',
                'title': 'Invalid Email Change!',
                'text': 'You attempted to change your email to an address that is invalid. Please enter a valid email address that is different from the current one.'
            }
        })
    if User.objects.filter(email=email_new).exists():
        messages.error(request, "This email is already in use.")
        return render(request, "error.html", {
            'error': {
                'class': 'danger',
                'title': 'Email Already In Use!',
                'text': 'You attempted to change your email to an address that is already in use.'
            }
        })

    token = secrets.token_urlsafe(32)
    cache.set(
        f"{EMAIL_CONFIRMATION_TOKEN_PREFIX}_{email_new}",
        {"token": token, "old_email": request.user.email},
        timeout=EMAIL_CONFIRMATION_TIMEOUT_SECONDS,
    )
    confirm_url = request.build_absolute_uri(
        reverse("optimap:confirm_email_change", args=[token, email_new])
    )
    subject = 'Confirm Your Email Change'
    message = f"""Hello,

You requested to change your email from {email_old} to {email_new}.
Please confirm the new email by clicking on this link:

{confirm_url}

This link will expire in 10 minutes.

Thank you for using OPTIMAP!
"""
    send_mail(subject, message, settings.EMAIL_HOST_USER, [email_new])
    messages.info(request, "A confirmation email has been sent.")
    logout(request)
    return render(request, 'changeuser.html')

def confirm_email_change(request, token, email_new):
    cached_data = cache.get(f"{EMAIL_CONFIRMATION_TOKEN_PREFIX}_{email_new}")
    if not cached_data:
        messages.error(request, "Invalid or expired confirmation link.")
        return HttpResponseRedirect("/")
    if isinstance(cached_data, str):
        messages.error(request, "Cache error: Expected dictionary, got string.")
        return HttpResponseRedirect("/")
    stored_token = cached_data.get("token")
    old_email = cached_data.get("old_email")
    if stored_token != token:
        messages.error(request, "Invalid or expired confirmation link.")
        return HttpResponseRedirect("/")
    user = User.objects.filter(email=old_email).first()
    if not user:
        messages.error(request, "User not found.")
        return HttpResponseRedirect("/")
    user.email = email_new
    user.username = email_new
    user.save()
    contactURL = f"{settings.BASE_URL}/contact"
    notify_subject = 'Your OPTIMAP Email Was Changed'
    notify_message = f"""Hello,

Your email associated with OPTIMAP was changed from {old_email} to {email_new}.
If you did NOT request this change, please contact us immediately at {contactURL}.

Thank you for using OPTIMAP!
"""
    send_mail(
        notify_subject,
        notify_message,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[old_email]
    )
    cache.delete(f"email_confirmation_{email_new}")
    login_user(request, user)
    messages.success(request, "Your email has been successfully updated!")
    return redirect("/usersettings/")

def get_login_link(request, email):
    token = secrets.token_urlsafe(nbytes=LOGIN_TOKEN_LENGTH)
    link = f"{request.scheme}://{request.site.domain}/login/{token}"

    # Store both email and next parameter in cache
    next_url = request.GET.get('next', request.POST.get('next', ''))
    # Ensure next_url is never empty - default to home page
    if not next_url or next_url.strip() == '':
        next_url = '/'
    cache_data = {'email': email, 'next': next_url}
    cache.set(token, cache_data, timeout=LOGIN_TOKEN_TIMEOUT_SECONDS)

    logger.info('Created login link for %s with token %s (next=%s) - %s', email, token, next_url, link)
    return link

def is_email_blocked(email):
    domain = email.split('@')[-1]
    if BlockedEmail.objects.filter(email=email).exists():
        return True
    if BlockedDomain.objects.filter(domain=domain).exists():
        return True
    return False

@login_required

def request_delete(request):
    user = request.user
    token = uuid.uuid4().hex
    cache.set(f"{USER_DELETE_TOKEN_PREFIX}_{token}", user.id, timeout=ACCOUNT_DELETE_TOKEN_TIMEOUT_SECONDS)
    confirm_url = request.build_absolute_uri(reverse('optimap:confirm_delete', args=[token]))
    timeout_minutes = ACCOUNT_DELETE_TOKEN_TIMEOUT_SECONDS // 60
    send_mail(
        'Confirm Your Account Deletion',
        f'Click the link to confirm deletion: {confirm_url}\n\n'
        f'This link is valid for {timeout_minutes} minutes. If you did not request this, ignore this email.',
        'no-reply@optimap.com',
        [user.email],
    )
    return redirect(reverse('optimap:usersettings') + '?message=Check your email for a confirmation link.')

@login_required(login_url='/')

def confirm_account_deletion(request, token):
    try:
        user_id = cache.get(f"{USER_DELETE_TOKEN_PREFIX}_{token}")
        if user_id is None:
            messages.error(request, "Invalid or expired deletion token.")
            return redirect(reverse('optimap:usersettings'))
        if request.user.id != user_id:
            messages.error(request, "You are not authorized to delete this account.")
            return redirect(reverse('optimap:main'))
        request.session[USER_DELETE_TOKEN_PREFIX] = token
        request.session.modified = True
        request.session.save()
        messages.warning(request, "Please confirm your account deletion. Your contributed data will remain on the platform.")
        return redirect(reverse('optimap:usersettings'))
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect(reverse('optimap:usersettings'))

@login_required(login_url='/')

def finalize_account_deletion(request):
    token = request.session.get(USER_DELETE_TOKEN_PREFIX)
    if not token:
        messages.error(request, "No active deletion request found.")
        return redirect(reverse('optimap:usersettings'))
    user_id = cache.get(f"{USER_DELETE_TOKEN_PREFIX}_{token}")
    if user_id is None:
        messages.error(request, "Invalid or expired deletion request.")
        return redirect(reverse('optimap:usersettings'))
    if request.user.id != user_id:
        messages.error(request, "You are not authorized to delete this account.")
        return redirect(reverse('optimap:main'))
    user = get_object_or_404(User, id=user_id)
    try:
        user.delete()
        logout(request)
        messages.success(request, "Your account has been successfully deleted.")
        return redirect(reverse('optimap:main'))
    except Exception as e:
        logger.error(f"Error deleting user {user.email}: {str(e)}")
        messages.error(request, "An error occurred while deleting your account. Please try again.")
        return redirect(reverse('optimap:usersettings'))
    finally:
        cache.delete(f"{USER_DELETE_TOKEN_PREFIX}_{token}")
        if USER_DELETE_TOKEN_PREFIX in request.session:
            del request.session[USER_DELETE_TOKEN_PREFIX]
            request.session.modified = True
