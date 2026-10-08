"""Let the repository's unittest discovery share the production package name.

The existing CI discovers from tests/, which places this directory before the
repository package. Extend the search path so all production submodules resolve
to email_intake/; no production module or version is copied into the tests.
"""
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
from .version import VERSION
