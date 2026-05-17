"""
Rate limiter singleton (slowapi / starlette).

Keyed on the client's remote IP address. Routes opt in via the @limiter.limit(...)
decorator — there is intentionally no global limit so only public-facing endpoints
(e.g. job application submission) are throttled.

The limiter instance must be attached to app.state.limiter in main.py so that
slowapi's _rate_limit_exceeded_handler can find it.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Single shared Limiter instance — imported by routes that need rate limiting
limiter = Limiter(key_func=get_remote_address)