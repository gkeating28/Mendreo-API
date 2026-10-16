"""Pick the host a browser can call back.

Pagination links are absolute URLs built from the request host. On Vercel the
function is reached at 127.0.0.1, and the unique deployment host
(``mendreo-<id>-mendreo1.vercel.app``) sits behind Vercel SSO. The public
alias does not. A ``next`` link aimed at either internal host never completes
in the browser, which surfaces as "Failed to fetch" after the first page.
"""


def _first(value: str | None) -> str:
    return (value or "").split(",")[0].strip()


def _hostname(value: str) -> str:
    return value.split(":")[0].strip().lower()


def _internal(host: str, deployment: str) -> bool:
    if not host:
        return True
    name = _hostname(host)
    # Django's test client. Leave it so local tests keep their own host.
    if name == "testserver":
        return False
    if name in {"127.0.0.1", "localhost", "lambda"}:
        return True
    if deployment and (host == deployment or name == _hostname(deployment)):
        return True
    return False


def choose_public_host(host: str | None, forwarded: str | None, deployment: str | None) -> str:
    """Return the host pagination links should use.

    A public Host is kept, so a caller cannot swap it for an arbitrary
    ``X-Forwarded-Host``. A loopback address or the Vercel deployment URL is
    replaced by the forwarded public host when that host is itself reachable.
    ``testserver`` is left alone so local tests keep their own host.
    """
    host = _first(host)
    forwarded = _first(forwarded)
    deployment = _first(deployment)
    if host and not _internal(host, deployment):
        return host
    if forwarded and not _internal(forwarded, deployment):
        return forwarded
    return host or forwarded
