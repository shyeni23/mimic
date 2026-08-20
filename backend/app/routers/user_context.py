from fastapi import APIRouter

from app.services.user_context import get_user_context

router = APIRouter(prefix="/api/user-context", tags=["user context (Module 1+2)"])


@router.get("/{session_id}")
def user_context(session_id: str):
    """Returns the combined user context for a session: visual profile
    (from the latest CV scan) + fashion preferences (from conversation
    state). Either side may be empty if no scan or conversation has
    happened yet."""
    return get_user_context(session_id)
