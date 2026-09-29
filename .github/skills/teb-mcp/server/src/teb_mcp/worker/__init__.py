"""32-bit worker package.

``teb_worker.py`` and ``teb_api.py`` are deliberately import-standalone: the
worker runs under a separate, minimal 32-bit interpreter that has no access to
this distribution's installed packages, so they must not import from
``teb_mcp``.
"""
