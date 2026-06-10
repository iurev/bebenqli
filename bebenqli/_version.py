"""Single source of truth for the package version.

pyproject.toml reads this via setuptools' dynamic-version `attr`, and the app
imports it directly — so the number lives in exactly one place."""
__version__ = "0.0.2"
