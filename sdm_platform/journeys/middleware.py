from django.conf import settings

from .models import Journey


class SubdomainJourneyMiddleware:
    """
    Detects subdomain and attaches the corresponding journey to the request.
    Example: backpain.corient.com -> request.journey_slug = 'backpain'
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.base_domain = getattr(settings, "BASE_DOMAIN", "clarenhealth.com")

    def __call__(self, request):
        # Extract subdomain
        host = request.get_host().split(":")[0]  # Remove port if present

        # Check if it's a subdomain
        if host.endswith(self.base_domain) and host != self.base_domain:
            subdomain = host.replace(f".{self.base_domain}", "")

            # Check if subdomain matches a journey
            try:
                journey = Journey.objects.get(slug=subdomain, is_active=True)
                request.journey_slug = journey.slug
                request.journey = journey
            except Journey.DoesNotExist:
                request.journey_slug = None
                request.journey = None
        else:
            request.journey_slug = None
            request.journey = None

        return self.get_response(request)
