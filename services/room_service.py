import random
import string
from datetime import datetime, timezone, timedelta
from services.supabase_client import supabase


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_code(length: int = 6) -> str:
    """Generate a random uppercase alphanumeric room code (e.g. 'A3BX92')."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def _unique_code(max_attempts: int = 5) -> str:
    """
    Attempt to generate a room code that doesn't already exist in the DB.

    Raises:
        RuntimeError: If a unique code cannot be found after max_attempts.
    """
    for _ in range(max_attempts):
        code = _generate_code()
        resp = supabase.table("rooms").select("id").eq("room_code", code).execute()
        if not resp.data:
            return code
    raise RuntimeError("Could not generate a unique room code. Please try again.")


# ---------------------------------------------------------------------------
# Room operations
# ---------------------------------------------------------------------------

def create_room(
    host_name: str,
    title: str,
    max_participants: int,
    suggestions_per_person: int,
    results_anonymous: bool = True,
    voting_method: str = "borda",
    host_lat: float | None = None,
    host_lng: float | None = None,
) -> dict:
    """
    Create a new room and immediately add the host as the first participant.
    """
    host_name = host_name.strip()
    title = title.strip()

    if not host_name:
        raise ValueError("host_name is required and cannot be blank.")
    if not title:
        raise ValueError("title is required and cannot be blank.")
    if not isinstance(max_participants, int) or max_participants < 2:
        raise ValueError("max_participants must be a positive integer.")
    if not isinstance(suggestions_per_person, int) or suggestions_per_person < 1:
        raise ValueError("suggestions_per_person must be a positive integer.")

    code = _unique_code()

    room_data = {
        "room_code":              code,
        "host_name":              host_name,
        "title":                  title,
        "max_participants":       max_participants,
        "suggestions_per_person": suggestions_per_person,
        "phase":                  "lobby",
        "results_anonymous":      results_anonymous,
        "voting_method":          voting_method,
    }
    if host_lat is not None and host_lng is not None:
        room_data["host_lat"] = host_lat
        room_data["host_lng"] = host_lng

    room_resp = supabase.table("rooms").insert(room_data).execute()

    if not room_resp.data:
        raise RuntimeError("Failed to create room — Supabase returned no data.")

    room = room_resp.data[0]

    # Host is automatically the first participant
    participant_resp = supabase.table("participants").insert({
        "room_id":      room["id"],
        "display_name": host_name,
    }).execute()

    if not participant_resp.data:
        raise RuntimeError("Room was created but failed to add host as participant.")

    return room


def get_room_by_code(room_code: str) -> dict | None:
    """Find a room by its join code (case-insensitive)."""
    resp = (
        supabase.table("rooms")
        .select("*")
        .eq("room_code", room_code.upper().strip())
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_nearby_rooms(lat: float, lng: float, radius_km: float = 1.0) -> list[dict]:
    """
    Return rooms in the lobby phase whose host location is within radius_km of (lat, lng).
    Only rooms where the host opted in by storing coordinates are considered.
    """
    from utils.helpers import haversine_km

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    resp = (
        supabase.table("rooms")
        .select("room_code, title, host_name, phase, host_lat, host_lng")
        .eq("phase", "lobby")
        .not_.is_("host_lat", "null")
        .not_.is_("host_lng", "null")
        .gte("created_at", cutoff)
        .execute()
    )

    results = []
    for room in (resp.data or []):
        dist = haversine_km(lat, lng, room["host_lat"], room["host_lng"])
        if dist <= radius_km:
            results.append({
                "title":       room["title"],
                "host_name":   room["host_name"],
                "code":        room["room_code"],
                "distance_km": round(dist, 2),
            })

    return sorted(results, key=lambda r: r["distance_km"])


def update_phase(room_id: str, phase: str) -> dict:
    """Advance a room to a new phase."""
    valid_phases = {"lobby", "suggesting", "voting", "results", "expired"}
    if phase not in valid_phases:
        raise ValueError(f"Invalid phase '{phase}'. Must be one of: {sorted(valid_phases)}.")

    existing = supabase.table("rooms").select("id").eq("id", room_id).execute()
    if not existing.data:
        raise ValueError(f"No room found with id '{room_id}'.")

    update_data: dict = {"phase": phase}
    if phase in ("suggesting", "voting"):
        update_data["phase_started_at"] = datetime.now(timezone.utc).isoformat()
    else:
        update_data["phase_started_at"] = None

    resp = (
        supabase.table("rooms")
        .update(update_data)
        .eq("id", room_id)
        .execute()
    )

    if not resp.data:
        raise RuntimeError("Phase update failed — Supabase returned no data.")

    return resp.data[0]


# ---------------------------------------------------------------------------
# Participant operations
# ---------------------------------------------------------------------------

def add_participant(room_id: str, display_name: str) -> dict:
    """Add a new participant to a room that is still in the lobby phase."""
    display_name = display_name.strip()

    if not display_name:
        raise ValueError("display_name is required and cannot be blank.")

    room_resp = (
        supabase.table("rooms")
        .select("phase, max_participants")
        .eq("id", room_id)
        .execute()
    )
    if not room_resp.data:
        raise ValueError("Room not found.")

    room = room_resp.data[0]

    if room["phase"] != "lobby":
        raise ValueError("This room has already started. You can no longer join.")

    current_participants = get_participants(room_id)

    if len(current_participants) >= room["max_participants"]:
        raise ValueError("This room is full.")

    existing_names = [p["display_name"].lower() for p in current_participants]
    if display_name.lower() in existing_names:
        raise ValueError(f"The name '{display_name}' is already taken in this room.")

    participant_resp = (
        supabase.table("participants")
        .insert({"room_id": room_id, "display_name": display_name})
        .execute()
    )

    if not participant_resp.data:
        raise RuntimeError("Failed to add participant — Supabase returned no data.")

    return participant_resp.data[0]


def get_participants(room_id: str) -> list[dict]:
    """Get all participants in a room, ordered by join time."""
    resp = (
        supabase.table("participants")
        .select("*")
        .eq("room_id", room_id)
        .order("joined_at")
        .execute()
    )
    return resp.data or []


def set_avatar(room_id: str, display_name: str, avatar: str) -> dict:
    """
    Save a participant's chosen avatar.

    Args:
        room_id:      UUID of the room.
        display_name: The participant's display name.
        avatar:       Avatar filename e.g. 'avatar_3.png'

    Returns:
        The updated participant record.

    Raises:
        ValueError:   If the participant is not found.
        RuntimeError: If the update fails.
    """
    resp = (
        supabase.table("participants")
        .update({"avatar": avatar})
        .eq("room_id", room_id)
        .eq("display_name", display_name)
        .execute()
    )

    if not resp.data:
        raise RuntimeError("Failed to update avatar — Supabase returned no data.")

    return resp.data[0]