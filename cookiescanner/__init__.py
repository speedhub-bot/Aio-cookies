"""Cookie-based session scanner.

Validates whether a stored cookie set is still alive for blackbox.ai,
manus.im, and perplexity.ai. When alive, extracts whatever account
information the site exposes to the authenticated browser session
(email, plan / tier, renewal date, credits, etc.).
"""

from .scanner import scan_all
from .types import ScanResult
from .cookies import load_cookies

__all__ = ["scan_all", "ScanResult", "load_cookies"]
__version__ = "0.1.0"
