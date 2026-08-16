"""Unit tests for Operator Profile Revision protocol."""
from __future__ import annotations

from src.warden.profile_protocol import compute_profile_revision


def test_profile_revision_stability():
    profile = {
        "name": "Matt",
        "email": "matt@example.com",
        "active_projects": ["Warden", "Grademy"],
        "current_priorities": ["Context Economy", "Captain Desk"],
        "preferences": {"mode": "dark"},
        "last_updated": "2026-08-16T12:00:00Z",
    }

    rev1 = compute_profile_revision(profile)
    assert rev1.startswith("prof_")

    # Timestamp update must NOT change profile revision
    profile_updated = dict(profile, last_updated="2026-08-16T14:00:00Z")
    rev2 = compute_profile_revision(profile_updated)
    assert rev1 == rev2, "Timestamp updates must not alter profile revision!"

    # Material priority change MUST change profile revision
    profile_changed = dict(profile, current_priorities=["New Priority"])
    rev3 = compute_profile_revision(profile_changed)
    assert rev1 != rev3, "Material priority change MUST alter profile revision!"
