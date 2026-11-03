"""Where patient records come from, set by CLINIC_SOURCE in backend/.env:

- "db" (default, production): the clinic database, read-only (app/clinic.py)
- "api": the colleague's Patient Intelligence API (app/clinic_api.py), while
  the database is suspended

Both have the same functions and return the same shapes, so the rest of the
app imports `clinic` from here and never knows which one it got.
"""
from app.config import settings

if settings.clinic_source == "api":
    from app import clinic_api as clinic
else:
    from app import clinic

USING_API = settings.clinic_source == "api"

__all__ = ["USING_API", "clinic"]
