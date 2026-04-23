from services.supabase_client import supabase


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def add_suggestion(room_id: str, participant_name: str, text: str) -> dict:
    """
    Add a suggestion for a participant.

    Args:
        room_id:          UUID of the room.
        participant_name: display_name of the person submitting.
        text:             The suggestion text.

    Returns:
        The newly created suggestion record as a dict.

    Raises:
        ValueError:   If any field is blank, the room isn't in the
                      'suggesting' phase, or the participant has already
                      used all their allowed suggestions.
        RuntimeError: If the Supabase insert fails unexpectedly.
    """
    text             = text.strip()
    participant_name = participant_name.strip()

    if not text:
        raise ValueError("Suggestion text cannot be blank.")
    if not participant_name:
        raise ValueError("participant_name cannot be blank.")

    # Fetch room to check phase, mode, and suggestions_per_person cap
    room_resp = (
        supabase.table("rooms")
        .select("phase, suggestions_per_person, room_mode, host_name")
        .eq("id", room_id)
        .execute()
    )
    if not room_resp.data:
        raise ValueError("Room not found.")

    room = room_resp.data[0]

    if room["phase"] != "suggesting":
        raise ValueError("Suggestions are not open for this room right now.")

    # In preset mode only the host may add options
    if room.get("room_mode") == "preset" and participant_name != room.get("host_name"):
        raise ValueError("This room is in preset mode. Only the host can add options.")

    # In open mode, enforce the per-person cap
    if room.get("room_mode", "open") == "open":
        existing = get_suggestions_by_participant(room_id, participant_name)
        if len(existing) >= room["suggestions_per_person"]:
            raise ValueError(
                f"You've already submitted all {room['suggestions_per_person']} "
                f"of your suggestion(s)."
            )

    resp = (
        supabase.table("suggestions")
        .insert({
            "room_id":          room_id,
            "participant_name": participant_name,
            "text":             text,
        })
        .execute()
    )

    if not resp.data:
        raise RuntimeError("Failed to save suggestion — Supabase returned no data.")

    return resp.data[0]


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_suggestions(room_id: str) -> list[dict]:
    """
    Return all suggestions for a room, ordered by submission time.

    Args:
        room_id: UUID of the room.

    Returns:
        List of suggestion records. Empty list if none yet.
    """
    resp = (
        supabase.table("suggestions")
        .select("*")
        .eq("room_id", room_id)
        .order("created_at")
        .execute()
    )
    return resp.data or []


def get_suggestions_by_participant(room_id: str, participant_name: str) -> list[dict]:
    """
    Return all suggestions submitted by one participant in a room.

    Args:
        room_id:          UUID of the room.
        participant_name: The participant's display_name.

    Returns:
        List of suggestion records. Empty list if none yet.
    """
    resp = (
        supabase.table("suggestions")
        .select("*")
        .eq("room_id", room_id)
        .eq("participant_name", participant_name)
        .order("created_at")
        .execute()
    )
    return resp.data or []


def get_suggestion_by_id(suggestion_id: str) -> dict | None:
    resp = (
        supabase.table("suggestions")
        .select("*")
        .eq("id", suggestion_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


def save_ai_description(suggestion_id: str, description: str) -> None:
    supabase.table("suggestions").update(
        {"ai_description": description}
    ).eq("id", suggestion_id).execute()


def get_suggestion_counts(room_id: str) -> dict[str, int]:
    """
    Return a dict mapping each participant_name to their submission count.
    Useful for showing progress on the suggestions page.

    Args:
        room_id: UUID of the room.

    Returns:
        e.g. {"Alex": 2, "Jordan": 1}
    """
    suggestions = get_suggestions(room_id)
    counts: dict[str, int] = {}
    for s in suggestions:
        name = s["participant_name"]
        counts[name] = counts.get(name, 0) + 1
    return counts


def mark_suggestions_done(room_id: str, participant_name: str) -> None:
    """Record that a participant has opted out of their remaining suggestion slots."""
    supabase.table("suggestions_done").upsert(
        {"room_id": room_id, "participant_name": participant_name},
        on_conflict="room_id,participant_name",
    ).execute()


def get_done_participants(room_id: str) -> set[str]:
    """Return the set of participant names who have marked themselves done early."""
    resp = (
        supabase.table("suggestions_done")
        .select("participant_name")
        .eq("room_id", room_id)
        .execute()
    )
    return {r["participant_name"] for r in (resp.data or [])}


def has_everyone_suggested(
    room_id: str,
    participants: list[dict],
    suggestions_per_person: int,
) -> bool:
    """Return True if every participant has hit their cap (or opted out with >=1) AND total >= 2."""
    if not participants:
        return False
    counts = get_suggestion_counts(room_id)
    done = get_done_participants(room_id)
    all_names = {p["display_name"] for p in participants}
    for name in all_names:
        submitted = counts.get(name, 0)
        hit_cap = submitted >= suggestions_per_person
        opted_out = name in done and submitted >= 1
        if not hit_cap and not opted_out:
            return False
    return sum(counts.values()) >= 2