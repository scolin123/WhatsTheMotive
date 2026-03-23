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
# Results — private helpers
# ---------------------------------------------------------------------------

def _calculate_borda(room_id: str, suggestions: list[dict]) -> list[dict]:
    """
    Borda-count scoring. rank 1 → N pts, rank 2 → N-1 pts, …, rank N → 1 pt.
    Returns results sorted best-first.
    """
    n = len(suggestions)
    by_id  = {s["id"]: s for s in suggestions}
    scores: dict[str, int] = {s["id"]: 0 for s in suggestions}

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
            scores[sid] += (n - rank + 1)

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


def _calculate_irv(room_id: str, suggestions: list[dict]) -> list[dict]:
    """
    Instant Runoff Voting (IRV) / Single Transferable Vote.

    Algorithm:
      1. Count each active candidate's first-choice votes from each ballot.
      2. If any candidate exceeds 50 % of total ballots cast, declare them winner.
      3. Otherwise eliminate the candidate(s) with the fewest first-choice votes
         and redistribute those ballots to each voter's next active choice.
      4. Repeat until a winner is found, or until remaining candidates are tied
         (in which case they all share first place).

    The ``score`` field in the returned dicts reflects each candidate's
    first-choice vote tally in the round they were decided (winners) or
    eliminated (losers), so the results page can display meaningful numbers.
    """
    if not suggestions:
        return []

    by_id = {s["id"]: s for s in suggestions}

    # ── Load all ballots ──────────────────────────────────────────────────────
    resp = (
        supabase.table("votes")
        .select("participant_name, suggestion_id, rank")
        .eq("room_id", room_id)
        .order("rank")
        .execute()
    )

    # ballots[participant] = [suggestion_id, ...] ordered rank-1 first
    ballots: dict[str, list[str]] = {}
    for vote in (resp.data or []):
        name = vote["participant_name"]
        ballots.setdefault(name, []).append(vote["suggestion_id"])

    total_ballots = len(ballots)

    if total_ballots == 0:
        # No votes yet — return suggestions in their original order
        return [
            {
                "id":               s["id"],
                "text":             s.get("text", ""),
                "participant_name": s.get("participant_name", ""),
                "score":            0,
                "position":         i + 1,
            }
            for i, s in enumerate(suggestions)
        ]

    active: set[str] = {s["id"] for s in suggestions}

    # Track elimination order so we can assign positions in reverse:
    # last eliminated → 2nd place, second-to-last → 3rd, etc.
    # Each entry is a list of (sid, score_at_elimination) tuples.
    elimination_rounds: list[list[tuple[str, int]]] = []

    # ── Main IRV loop ─────────────────────────────────────────────────────────
    while True:
        # Count first-choice votes among still-active candidates
        counts: dict[str, int] = {sid: 0 for sid in active}
        for ballot in ballots.values():
            for sid in ballot:
                if sid in active:
                    counts[sid] += 1
                    break

        # ── Majority check ────────────────────────────────────────────────────
        winner_sid = next(
            (sid for sid, c in counts.items() if c > total_ballots / 2),
            None,
        )
        if winner_sid is not None:
            results = [
                {
                    "id": winner_sid,
                    "text": by_id[winner_sid].get("text", ""),
                    "participant_name": by_id[winner_sid].get("participant_name", ""),
                    "score": counts[winner_sid],
                    "position": 1,
                }
            ]

            # Add remaining active candidates (excluding winner), ranked by current round count
            remaining = [sid for sid in active if sid != winner_sid]
            remaining_sorted = sorted(remaining, key=lambda sid: counts[sid], reverse=True)

            position = 2
            for sid in remaining_sorted:
                suggestion = by_id.get(sid, {})
                results.append({
                    "id": sid,
                    "text": suggestion.get("text", ""),
                    "participant_name": suggestion.get("participant_name", ""),
                    "score": counts[sid],
                    "position": position,
                })
                position += 1

            # Then append previously eliminated candidates
            for round_group in reversed(elimination_rounds):
                for sid, score in round_group:
                    suggestion = by_id.get(sid, {})
                    results.append({
                        "id": sid,
                        "text": suggestion.get("text", ""),
                        "participant_name": suggestion.get("participant_name", ""),
                        "score": score,
                        "position": position,
                    })
                    position += 1

            return results

        # ── Tie / exhaustion check ────────────────────────────────────────────
        # Find the minimum vote count among active candidates
        min_votes = min(counts.values())
        to_eliminate = {sid for sid, c in counts.items() if c == min_votes}

        # If ALL remaining candidates are tied, declare them joint winners
        if to_eliminate == active:
            results = []
            # Sort tied candidates by their id for a deterministic order
            for position, sid in enumerate(sorted(active), start=1):
                suggestion = by_id.get(sid, {})
                results.append({
                    "id":               sid,
                    "text":             suggestion.get("text", ""),
                    "participant_name": suggestion.get("participant_name", ""),
                    "score":            counts[sid],
                    "position":         position,
                })
            # Append previously eliminated candidates
            position = len(active) + 1
            for round_group in reversed(elimination_rounds):
                for sid, score in round_group:
                    suggestion = by_id.get(sid, {})
                    results.append({
                        "id":               sid,
                        "text":             suggestion.get("text", ""),
                        "participant_name": suggestion.get("participant_name", ""),
                        "score":            score,
                        "position":         position,
                    })
                    position += 1
            return results

        # ── Eliminate the weakest candidate(s) ───────────────────────────────
        round_group = [(sid, counts[sid]) for sid in sorted(to_eliminate)]
        elimination_rounds.append(round_group)
        active -= to_eliminate


# ---------------------------------------------------------------------------
# Results — public entry point
# ---------------------------------------------------------------------------

def calculate_results(room_id: str, suggestions: list[dict]) -> list[dict]:
    """
    Calculate results for all suggestions and return them sorted best-first.

    The scoring method is determined by the ``voting_method`` column on the
    room: ``'borda'`` (default) uses Borda-count points; ``'irv'`` uses
    Instant Runoff Voting.

    Args:
        room_id:     UUID of the room.
        suggestions: List of suggestion dicts with at least ``'id'`` and
                     ``'text'``.

    Returns:
        List of result dicts sorted by position ascending::

            [
                {
                    "id":               "...",
                    "text":             "Inception",
                    "participant_name": "Alex",
                    "score":            18,      # pts (Borda) or first-choice votes (IRV)
                    "position":         1,       # 1-indexed final rank
                },
                ...
            ]
    """
    if not suggestions:
        return []

    # Fetch the room's voting method
    room_resp = (
        supabase.table("rooms")
        .select("voting_method")
        .eq("id", room_id)
        .execute()
    )
    voting_method = "borda"  # safe default
    if room_resp.data:
        voting_method = room_resp.data[0].get("voting_method") or "borda"

    if voting_method == "irv":
        return _calculate_irv(room_id, suggestions)

    # Default: Borda count
    return _calculate_borda(room_id, suggestions)