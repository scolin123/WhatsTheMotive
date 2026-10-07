from services.supabase_client import supabase

RUNOFF_SIZE = 3


# ---------------------------------------------------------------------------
# Room state
# ---------------------------------------------------------------------------

def set_runoff_status(room_id: str, status: str | None) -> dict:
    """Set the room's runoff_status to None, 'voting', or 'done'."""
    if status not in (None, "voting", "done"):
        raise ValueError(f"Invalid runoff status '{status}'.")

    resp = (
        supabase.table("rooms")
        .update({"runoff_status": status})
        .eq("id", room_id)
        .execute()
    )
    if not resp.data:
        raise RuntimeError("Runoff update failed — Supabase returned no data.")
    return resp.data[0]


def get_runoff_candidates(results: list[dict]) -> list[dict]:
    """
    Return the top entries from round-one results that go into the runoff.

    Round-one votes are locked once the room leaves the voting phase, so this
    is stable for the life of the runoff.
    """
    return results[:RUNOFF_SIZE]


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_runoff_vote(
    room_id: str,
    participant_name: str,
    suggestion_id: str,
    candidate_ids: set[str],
) -> None:
    """
    Save (or replace) a participant's single runoff vote.

    Raises:
        ValueError:   If the runoff isn't open or the pick isn't a candidate.
        RuntimeError: If the Supabase insert fails.
    """
    room_resp = (
        supabase.table("rooms")
        .select("runoff_status")
        .eq("id", room_id)
        .execute()
    )
    if not room_resp.data:
        raise ValueError("Room not found.")
    if room_resp.data[0].get("runoff_status") != "voting":
        raise ValueError("The runoff is not open right now.")
    if suggestion_id not in candidate_ids:
        raise ValueError("Pick one of the runoff options.")

    supabase.table("runoff_votes") \
        .delete() \
        .eq("room_id", room_id) \
        .eq("participant_name", participant_name) \
        .execute()

    resp = supabase.table("runoff_votes").insert({
        "room_id":          room_id,
        "participant_name": participant_name,
        "suggestion_id":    suggestion_id,
    }).execute()
    if not resp.data:
        raise RuntimeError("Failed to save vote — Supabase returned no data.")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_runoff_votes(room_id: str) -> list[dict]:
    """Return every runoff vote as {participant_name, suggestion_id}."""
    resp = (
        supabase.table("runoff_votes")
        .select("participant_name, suggestion_id")
        .eq("room_id", room_id)
        .execute()
    )
    return resp.data or []


def has_everyone_runoff_voted(room_id: str, participants: list[dict]) -> bool:
    """Return True if every participant has cast a runoff vote."""
    if not participants:
        return False
    voter_names = {v["participant_name"] for v in get_runoff_votes(room_id)}
    return {p["display_name"] for p in participants} <= voter_names


def calculate_runoff_results(candidates: list[dict], votes: list[dict]) -> list[dict]:
    """
    Tally runoff votes and return the candidates sorted best-first.

    Ties are broken by round-one position, so the earlier favourite wins.
    Each returned dict is the candidate plus ``votes`` and a new ``position``.
    """
    counts = {c["id"]: 0 for c in candidates}
    for v in votes:
        if v["suggestion_id"] in counts:
            counts[v["suggestion_id"]] += 1

    ordered = sorted(candidates, key=lambda c: (-counts[c["id"]], c["position"]))
    return [
        {**c, "votes": counts[c["id"]], "position": i}
        for i, c in enumerate(ordered, start=1)
    ]
