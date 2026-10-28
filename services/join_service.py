"""Join requests for private rooms: a person asks, the host accepts or denies."""
from services.supabase_client import supabase
from services.room_service import add_participant, get_participants


def create_request(room_id: str, display_name: str) -> None:
    """
    Record (or reset to pending) a request to join a private room.

    Raises:
        ValueError: If the room isn't in the lobby or the name is already in use.
    """
    display_name = display_name.strip()
    room_resp = supabase.table("rooms").select("phase").eq("id", room_id).execute()
    if not room_resp.data:
        raise ValueError("Room not found.")
    if room_resp.data[0]["phase"] != "lobby":
        raise ValueError("This room has already started. You can no longer join.")

    taken = {p["display_name"].lower() for p in get_participants(room_id)}
    if display_name.lower() in taken:
        raise ValueError("That name is already in use in this room. Please choose a different name.")

    # Upsert so asking again after a denial puts the request back to pending.
    supabase.table("join_requests").upsert(
        {"room_id": room_id, "display_name": display_name, "status": "pending"},
        on_conflict="room_id,display_name",
    ).execute()


def get_pending_requests(room_id: str) -> list[dict]:
    """Return pending requests for a room, oldest first."""
    resp = (
        supabase.table("join_requests")
        .select("display_name, created_at")
        .eq("room_id", room_id)
        .eq("status", "pending")
        .order("created_at")
        .execute()
    )
    return resp.data or []


def get_request_status(room_id: str, display_name: str) -> str | None:
    """Return 'pending', 'approved' or 'denied', or None if there is no request."""
    resp = (
        supabase.table("join_requests")
        .select("status")
        .eq("room_id", room_id)
        .eq("display_name", display_name)
        .execute()
    )
    return resp.data[0]["status"] if resp.data else None


def resolve_request(room_id: str, display_name: str, approve: bool) -> None:
    """
    Mark a pending request approved or denied.

    Approving does NOT add the person to the room yet: their own browser does
    that (see claim_approved) when it sees the approval. That way someone who
    closed the page before being let in never becomes a ghost participant who
    blocks "everyone has voted".

    Raises:
        ValueError: If there's no pending request, or the room is full / started.
    """
    if get_request_status(room_id, display_name) != "pending":
        raise ValueError("That request is no longer pending.")

    if approve:
        room_resp = (
            supabase.table("rooms").select("phase, max_participants").eq("id", room_id).execute()
        )
        if not room_resp.data or room_resp.data[0]["phase"] != "lobby":
            raise ValueError("This room has already started.")
        if len(get_participants(room_id)) >= room_resp.data[0]["max_participants"]:
            raise ValueError("This room is full.")

    supabase.table("join_requests").update(
        {"status": "approved" if approve else "denied"}
    ).eq("room_id", room_id).eq("display_name", display_name).execute()


def claim_approved(room_id: str, display_name: str) -> None:
    """
    Add an approved person to the room. Called from their own browser once it
    sees the approval. Safe to call twice (a second call does nothing).

    Raises:
        ValueError: If the room filled up or started in the meantime.
    """
    already_in = any(
        p["display_name"].lower() == display_name.lower()
        for p in get_participants(room_id)
    )
    if not already_in:
        add_participant(room_id=room_id, display_name=display_name)
