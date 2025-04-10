import logging
logger = logging.getLogger(__name__)

from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.core.cache import cache
from django.http.request import HttpRequest
from django.http import HttpResponseRedirect, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.core.mail import EmailMessage, send_mail, get_connection
from django.views.generic import View
import secrets
from django.contrib import messages
from django.contrib.auth import login,logout
from django.views.decorators.http import require_GET
from publications.models import BlockedEmail, BlockedDomain
from django.conf import settings
from publications.models import Subscription
from datetime import datetime
import imaplib
import time
from math import floor
from django_currentuser.middleware import (get_current_user, get_current_authenticated_user)
from django.shortcuts import redirect, get_object_or_404
from urllib.parse import unquote
from django.urls import reverse
import uuid
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.utils.timezone import now
from django.contrib.auth import get_user_model
User = get_user_model()
from publications.models import UserProfile
from django.views.decorators.cache import never_cache
from django.urls import reverse  

LOGIN_TOKEN_LENGTH  = 32
LOGIN_TOKEN_TIMEOUT_SECONDS = 10 * 60
EMAIL_CONFIRMATION_TIMEOUT_SECONDS = 10 * 60
ACCOUNT_DELETE_TOKEN_TIMEOUT_SECONDS = 10 * 60
USER_DELETE_TOKEN_PREFIX = "user_delete_token" 

def main(request):
    return render(request,"main.html")

def loginres(request):
    email = request.POST.get('email', False)
    
    if is_email_blocked(email):
        logger.warning('Attempted login with blocked email: %s', email)
        return render(request, "error.html", {
            'error': {
                'class': 'danger',
                'title': 'Login failed!',
                'text': 'You attempted to login using an email that is blocked. Please contact support for assistance.'
            }
        })

    subject = 'OPTIMAP Login'
    link = get_login_link(request, email)
    valid = floor(LOGIN_TOKEN_TIMEOUT_SECONDS / 60)
    body = f"""Hello {email} !

You requested that we send you a link to log in to OPTIMAP at {request.site.domain}:

{link}

Please click on the link to log in.
The link is valid for {valid} minutes.
"""

    logging.info('Login process started for user %s', email)
    try:
        email_message = EmailMessage(
            subject = subject,
            body = body,
            from_email = settings.EMAIL_HOST_USER,
            to = [email],
            headers={'OPTIMAP': request.site.domain}
            )
        result = email_message.send()
        logging.info('%s sent login email to %s with the result: %s', settings.EMAIL_HOST_USER, email_message.recipients(), result)
        
        # If backend is SMTP, then put the sent email into the configured folder, see also https://stackoverflow.com/a/59735890/261210
        if str(get_connection().__class__.__module__).endswith("smtp"):
            with imaplib.IMAP4_SSL(settings.EMAIL_HOST_IMAP, port = settings.EMAIL_PORT_IMAP) as imap:
                message = str(email_message.message()).encode()
                imap.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
                # must make sure the folder exists
                folder = settings.EMAIL_IMAP_SENT_FOLDER
                imap.append(folder, '\\Seen', imaplib.Time2Internaldate(time.time()), message)
                logging.debug('Saved email to IMAP folder {folder}')
                
        return render(request,'login_response.html', {
            'email': email,
            'valid_minutes': valid,
        })
    except Exception as ex:
        logging.exception('Error sending login email to %s from %s', email, settings.EMAIL_HOST_USER)
        logging.error(ex)
        return render(request, "error.html", {
            'error': {
                'class': 'danger',
                'title': 'Login failed!',
                'text': 'Error sending the login email. Please try again or contact us!'
            }
        })

def privacy(request):
    return render(request,'privacy.html')

def data(request):
    return render(request,'data.html')

def Confirmationlogin(request):
    return render(request,'confirmation_login.html')

def login_user(request, user):
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    #user.last_login = now # this should be set by Django's UserManager
    user.save()

@require_GET
def authenticate_via_magic_link(request: HttpRequest, token: str):
    email = cache.get(token)
    logger.info('Authenticating magic link with token %s: Found user: %s', token, email)

    if email is None:
        logger.debug('Magic link invalid for user %s', email)
        return render(request, "error.html", {
            'error': {
                'class': 'danger',
                'title': 'Authentication failed!',
                'text': 'Magic link invalid or expired. Please try again!'
            }
        })

    user = User.objects.filter(email=email).first()

    if user:
        if user.deleted:
            # Create a new user if existing record is found
            user.deleted = False
            user.deleted_at = None
            user.is_active = True  
            user.save()
            is_new = False  
        else:
            is_new = False  
    else:
        # Create a new user if no existing record is found
        user = User.objects.create_user(username=email, email=email)
        is_new = True

    login_user(request, user)

    cache.delete(token)
    return render(request, "confirmation_login.html", {
        'is_new': is_new
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
        "delete_token": request.session.get(USER_DELETE_TOKEN_PREFIX, None),  # Fetch token from session
    })

def user_subscriptions(request):
    if request.user.is_authenticated:
        subs = Subscription.objects.all()
        count_subs = Subscription.objects.all().count()
        return render(request,'subscriptions.html',{'sub':subs,'count':count_subs})
    else:
        pass

def add_subscriptions(request):
    if request.method == "POST":
        search_term = request.POST.get("search", False)
        start_date = request.POST.get('start_date', False)
        end_date = request.POST.get('end_date', False)
        currentuser = request.user
        if currentuser.is_authenticated:            
            user_name = currentuser.username
        else : 
            user_name = None
        start_date_object = datetime.strptime(start_date, '%m/%d/%Y')
        end_date_object = datetime.strptime(end_date, '%m/%d/%Y')
        
        # save info in db
        subscription = Subscription(search_term = search_term, timeperiod_startdate = start_date_object, timeperiod_enddate = end_date_object, user_name = user_name )
        logger.info('Adding new subscription for user %s: %s', user_name, subscription)
        subscription.save()
        return  HttpResponseRedirect('/subscriptions/')

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

    Current_user = User.objects.filter(email = email)
    Current_user.delete()
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
        messages.error(request, "Invalid email change request.")
        return render(request, 'changeuser.html')

    if not email_new or email_new == email_old:
        messages.error(request, "Invalid email change request.")
        return render(request, 'changeuser.html')

    if User.objects.filter(email=email_new).exists():
        messages.error(request, "This email is already in use.")
        return render(request, 'changeuser.html')

    token = secrets.token_urlsafe(32)
    cache.set(
        f"email_confirmation_{email_new}",
        {"token": token, "old_email": request.user.email}, 
        timeout=EMAIL_CONFIRMATION_TIMEOUT_SECONDS,
    )

    confirm_url = request.build_absolute_uri(
        reverse("optimap:confirm-email-change", args=[token, email_new])
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
    cached_data = cache.get(f"email_confirmation_{email_new}")

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
    token = secrets.token_urlsafe(nbytes = LOGIN_TOKEN_LENGTH)
    link = f"{request.scheme}://{request.site.domain}/login/{token}"
    cache.set(token, email, timeout = LOGIN_TOKEN_TIMEOUT_SECONDS)
    logger.info('Created login link for %s with token %s - %s', email, token, link)
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

    timeout_minutes = ACCOUNT_DELETE_TOKEN_TIMEOUT_SECONDS//60

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

        # Ensure the logged-in user matches the user stored in the token
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

    if user.deleted:
        messages.warning(request, "This account has already been deleted.")
        return redirect(reverse('optimap:usersettings'))

    try:
        user.deleted = True
        user.deleted_at = now()
        user.save()
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

class RobotsView(View):
    http_method_names = ['get']

    def get(self, request):
        response = HttpResponse("User-Agent: *\nDisallow:\nSitemap: %s://%s/sitemap.xml" % (request.scheme, request.site.domain),
                                content_type = "text/plain")

        return response
