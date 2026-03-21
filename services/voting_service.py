from services.supabase_client import supabase


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_vote(room_id: str, participant_name: str, ranked_suggestion_ids: list[str]) -> None:
    """
    Save (or replace) a participant's ranked vote for a room.

    ranked_suggestion_ids is an ordered list where index 0 = 1st choice.
    Deletes any existing vote from this participant first, then inserts fresh
    rows — this is the simplest correct way to handle re-votes.

    Args:
        room_id:               UUID of the room.
        participant_name:      The voter's display_name.
        ranked_suggestion_ids: Suggestion UUIDs in ranked order (best first).

    Raises:
        ValueError:   If the list is empty, the room isn't in 'voting' phase,
                      or the IDs don't match the room's suggestions.
        RuntimeError: If the Supabase insert fails.
    """
    if not ranked_suggestion_ids:
        raise ValueError("You must rank at least one suggestion.")

    # Confirm room is in voting phase
    room_resp = (
        supabase.table("rooms")
        .select("phase")
        .eq("id", room_id)
        .execute()
    )
    if not room_resp.data:
        raise ValueError("Room not found.")
    if room_resp.data[0]["phase"] != "voting":
        raise ValueError("Voting is not open for this room right now.")

    # Delete existing vote from this participant
    supabase.table("votes") \
        .delete() \
        .eq("room_id", room_id) \
        .eq("participant_name", participant_name) \
        .execute()

    # Insert new ranked rows  (rank 1 = best choice)
    rows = [
        {
            "room_id":          room_id,
            "participant_name": participant_name,
            "suggestion_id":    sid,
            "rank":             i + 1,
        }
        for i, sid in enumerate(ranked_suggestion_ids)
    ]
    resp = supabase.table("votes").insert(rows).execute()
    if not resp.data:
        raise RuntimeError("Failed to save vote — Supabase returned no data.")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_vote_by_participant(room_id: str, participant_name: str) -> list[dict]:
    """
    Return one participant's current vote, ordered best-first (rank ASC).
    Returns an empty list if they haven't voted yet.
    """
    resp = (
        supabase.table("votes")
        .select("suggestion_id, rank")
        .eq("room_id", room_id)
        .eq("participant_name", participant_name)
        .order("rank")
        .execute()
    )
    return resp.data or []


def get_voters(room_id: str) -> list[str]:
    """
    Return a list of distinct participant_names who have submitted a vote.
    """
    resp = (
        supabase.table("votes")
        .select("participant_name")
        .eq("room_id", room_id)
        .execute()
    )
    seen = set()
    voters = []
    for row in (resp.data or []):
        name = row["participant_name"]
        if name not in seen:
            seen.add(name)
            voters.append(name)
    return voters


def has_everyone_voted(room_id: str, participants: list[dict]) -> bool:
    """
    Return True if every participant has submitted a vote.

    Args:
        room_id:      UUID of the room.
        participants: List of participant dicts (must have 'display_name').
    """
    if not participants:
        return False
    voter_names  = set(get_voters(room_id))
    all_names    = {p["display_name"] for p in participants}
    return all_names == voter_names


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def calculate_results(room_id: str, suggestions: list[dict]) -> list[dict]:
    """
    Calculate Borda-count scores for all suggestions and return them
    sorted best-first.

    Scoring: with N suggestions, rank 1 earns N points, rank 2 earns N-1, …,
    rank N earns 1 point. This is summed across all voters.

    Args:
        room_id:     UUID of the room.
        suggestions: List of suggestion dicts with at least 'id' and 'text'.

    Returns:
        List of dicts sorted by score descending:
            [
                {
                    "id":               "...",
                    "text":             "Inception",
                    "participant_name": "Alex",
                    "score":            18,
                    "position":         1,       # 1-indexed final rank
                },
                ...
            ]
    """
    n = len(suggestions)
    if n == 0:
        return []

    # Build lookup: suggestion_id → suggestion dict
    by_id = {s["id"]: s for s in suggestions}

    # Initialise score map
    scores: dict[str, int] = {s["id"]: 0 for s in suggestions}

    # Fetch all votes for the room
    resp = (
        supabase.table("votes")
        .select("suggestion_id, rank")
        .eq("room_id", room_id)
        .execute()
    )

    for vote in (resp.data or []):
        sid  = vote["suggestion_id"]
        rank = vote["rank"]
        if sid in scores:
            scores[sid] += (n - rank + 1)   # rank 1 → n pts, rank n → 1 pt

    # Build sorted result list
    sorted_ids = sorted(scores.keys(), key=lambda sid: scores[sid], reverse=True)

    results = []
    for position, sid in enumerate(sorted_ids, start=1):
        suggestion = by_id.get(sid, {})
        results.append({
            "id":               sid,
            "text":             suggestion.get("text", ""),
            "participant_name": suggestion.get("participant_name", ""),
            "score":            scores[sid],
            "position":         position,
        })

    return results