from .public_host import choose_public_host


class PublicHostMiddleware:
    """Point absolute URLs at the host the browser already used.

    Runs before Django builds ``request.get_host()``. When the socket host is
    the loopback proxy or the protected deployment URL, the forwarded public
    host replaces it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        meta = request.META
        chosen = choose_public_host(
            meta.get("HTTP_HOST"),
            meta.get("HTTP_X_FORWARDED_HOST"),
            meta.get("HTTP_X_VERCEL_DEPLOYMENT_URL"),
        )
        if chosen:
            # Keep Host and X-Forwarded-Host on the same public name.
            # Django prefers the forwarded host, so leaving a deployment URL
            # there would put pagination links back on the protected host.
            meta["HTTP_HOST"] = chosen
            meta["HTTP_X_FORWARDED_HOST"] = chosen
        return self.get_response(request)
