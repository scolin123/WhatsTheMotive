import random
import string
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
) -> dict:
    """
    Create a new room and immediately add the host as the first participant.

    Args:
        host_name:            Display name of the host.
        title:                A short label for the session (e.g. 'Friday plans').
        max_participants:     Hard cap on how many people can join.
        suggestions_per_person: How many suggestions each participant may submit.

    Returns:
        The newly created room record as a dict.

    Raises:
        ValueError: If any required field is missing or blank.
        RuntimeError: If the insert fails unexpectedly.
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

    room_resp = supabase.table("rooms").insert({
        "room_code": code,
        "host_name": host_name,
        "title": title,
        "max_participants": max_participants,
        "suggestions_per_person": suggestions_per_person,
        "phase": "lobby",
    }).execute()

    if not room_resp.data:
        raise RuntimeError("Failed to create room — Supabase returned no data.")

    room = room_resp.data[0]

    # Host is automatically the first participant
    participant_resp = supabase.table("participants").insert({
        "room_id": room["id"],
        "display_name": host_name,
    }).execute()

    if not participant_resp.data:
        raise RuntimeError("Room was created but failed to add host as participant.")

    return room


def get_room_by_code(room_code: str) -> dict | None:
    """
    Find a room by its join code (case-insensitive).

    Args:
        room_code: The room code to look up.

    Returns:
        The room record as a dict, or None if not found.
    """
    resp = (
        supabase.table("rooms")
        .select("*")
        .eq("room_code", room_code.upper().strip())
        .execute()
    )
    return resp.data[0] if resp.data else None


def update_phase(room_id: str, phase: str) -> dict:
    """
    Advance a room to a new phase.

    Valid transitions: 'lobby' → 'suggesting' → 'voting' → 'results'

    Args:
        room_id: UUID of the room.
        phase:   The target phase.

    Returns:
        The updated room record as a dict.

    Raises:
        ValueError: If the phase is invalid or the room does not exist.
    """
    valid_phases = {"lobby", "suggesting", "voting", "results"}
    if phase not in valid_phases:
        raise ValueError(f"Invalid phase '{phase}'. Must be one of: {sorted(valid_phases)}.")

    # Confirm room exists before attempting update
    existing = supabase.table("rooms").select("id").eq("id", room_id).execute()
    if not existing.data:
        raise ValueError(f"No room found with id '{room_id}'.")

    resp = (
        supabase.table("rooms")
        .update({"phase": phase})
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
    """
    Add a new participant to a room that is still in the lobby phase.

    Args:
        room_id:      UUID of the room to join.
        display_name: The name this participant will go by.

    Returns:
        The newly created participant record as a dict.

    Raises:
        ValueError: If the room doesn't exist, has already started,
                    is full, or the display name is taken (case-insensitive).
        RuntimeError: If the insert fails unexpectedly.
    """
    display_name = display_name.strip()

    if not display_name:
        raise ValueError("display_name is required and cannot be blank.")

    # Fetch room to validate phase and capacity in one query
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

    # Fetch current participants to check capacity and name uniqueness together
    current_participants = get_participants(room_id)

    if len(current_participants) >= room["max_participants"]:
        raise ValueError("This room is full.")

    # Case-insensitive duplicate name check
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
    """
    Get all participants in a room, ordered by join time.

    Args:
        room_id: UUID of the room.

    Returns:
        List of participant records as dicts. Empty list if none found.
    """
    resp = (
        supabase.table("participants")
        .select("*")
        .eq("room_id", room_id)
        .order("joined_at")
        .execute()
    )
    return resp.data or []