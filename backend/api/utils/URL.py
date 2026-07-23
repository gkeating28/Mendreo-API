import tldextract

def clean(url):

    if url is None:
        return None

    naked_domain = domain(url) + "." + top_level_domain(url)

    if subdomain(url):
        return subdomain(url) + "." + naked_domain

    return naked_domain


def naked_domain(url):
    return domain(url) + "." + top_level_domain(url)


def domain(url):
    return tldextract.extract(url).domain


def subdomain(url):
    return tldextract.extract(url).subdomain


def top_level_domain(url):
    return tldextract.extract(url).suffix