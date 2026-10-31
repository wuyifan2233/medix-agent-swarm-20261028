"""Create, list, update and cancel reminders. Identity comes from the server."""
from typing import Any, Dict, Optional

from reminders.context import current_identity
from reminders.service import get_service


async def scheduled_reminder(
    action: str,
    kind: Optional[str] = None,
    repeat: Optional[str] = None,
    fire_at: Optional[str] = None,
    times: Optional[str] = None,
    weekdays: Optional[str] = None,
    drug: Optional[str] = None,
    dose: Optional[str] = None,
    location: Optional[str] = None,
    note: Optional[str] = None,
    reminder_id: Optional[str] = None,
) -> Dict[str, Any]:
    user_id, session_id = current_identity()
    if not user_id or not session_id:
        return {"success": False, "needs_clarification": True, "question": "提醒只能在当前网页对话里设置。"}
    return get_service().handle(
        user_id, session_id, action=action, kind=kind, repeat=repeat, fire_at=fire_at, times=times,
        weekdays=weekdays, drug=drug, dose=dose, location=location, note=note, reminder_id=reminder_id)
