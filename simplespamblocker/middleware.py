# -*- coding: utf-8 -*-
import re
import logging
from django.conf import settings
from django.contrib.sites.models import get_current_site
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden
from django.template import loader, RequestContext
from django.utils import simplejson as json
from simplespamblocker.models import Option
from simplespamblocker import settings as app_settings


class SpamBlockMiddleware(object):

    def __init__(self):
        self.block_profiles = []
        for path, profile in getattr(settings, 'SIMPLESPAMBLOCKER_PROFILES', []):
            regex = re.compile(path)
            self.block_profiles.append((regex, profile))
        if app_settings.LOGGER_NAME:
            self.logger = logging.getLogger(name=app_settings.LOGGER_NAME)
        else:
            self.logger = None

    def _get_regexes(self, site):
        cache_key = Option.get_cache_key(site)
        regexes = cache.get(cache_key)
        if not regexes:
            try:
                option = Option.objects.get(site=site)
            except Option.DoesNotExist:
                return None
            regexes = option.compile_regexes()
            cache.set(cache_key, regexes)
        return regexes

    def _logging(self, message):
        if self.logger:
            self.logger.info(message)

    def _is_spam(self, request, profile):
        site = get_current_site(request)
        regexes = self._get_regexes(site)
        if regexes is None:
            return False
        for key, regex in regexes.items():
            if key in ('remote_addr', 'http_referer', 'http_user_agent'):
                value = request.META.get(key.upper(), '')
            else:
                value = profile[key](request)
            if regexes[key] and regexes[key].search(value):
                self._logging(u'Blocked spam by %s: %s' % (key, value))
                self._logging(json.dumps(request.POST))
                return True
        return False

    def _get_block_profile(self, path_info):
        for regex, profile in self.block_profiles:
            if regex.search(path_info):
                return profile
        return None

    def process_view(self, request, view_func, view_args, view_kwargs):
        profile = self._get_block_profile(request.path_info)
        if profile and self._is_spam(request, profile):
            if app_settings.SPAM_TEMPLATE:
                rendered = loader.render_to_string(
                    app_settings.SPAM_TEMPLATE,
                    context_instance=RequestContext(request))
                return HttpResponse(rendered, status=403)
            else:
                return HttpResponseForbidden('Your comment was detected as a SPAM')
        return view_func(request, *view_args, **view_kwargs)