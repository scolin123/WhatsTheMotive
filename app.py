from datetime import datetime, timezone, timedelta
from better_profanity import profanity
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash,
)
from config import Config
from services.room_service import (
    create_room,
    get_nearby_rooms,
    get_room_by_code,
    add_participant,
    get_participants,
    update_phase,
    set_avatar,
)
from services.suggestion_service import (
    add_suggestion,
    get_suggestions,
    get_suggestions_by_participant,
    get_suggestion_by_id,
    save_ai_description,
    has_everyone_suggested,
    mark_suggestions_done,
    get_done_participants,
)
from services.ai_service import generate_suggestion_description
from services.voting_service import (
    save_vote,
    get_vote_by_participant,
    get_voters,
    has_everyone_voted,
    calculate_results,
)

app = Flask(__name__)
app.config.from_object(Config)
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True

# Add this near the top of app.py
VOTING_METHODS = {
    "borda": "Borda Count",
    "irv": "Instant Runoff (Elimination)"
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _phase_deadline(room: dict) -> str | None:
    """Return the ISO deadline for the current timed phase, or None."""
    started = room.get("phase_started_at")
    if not started:
        return None
    timer_secs = min(room.get("suggestions_per_person", 1), 5) * 60
    dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
    return (dt + timedelta(seconds=timer_secs)).isoformat()


def _require_session(code: str):
    """
    Return (display_name, is_host) from session if valid for this room code,
    or (None, None) if the session is missing or mismatched.
    """
    if "display_name" not in session or session.get("room_code") != code:
        return None, None
    return session["display_name"], session.get("is_host", False)


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Create room
# ---------------------------------------------------------------------------

@app.route("/room/create", methods=["GET"])
def create_room_page():
    return render_template("create_room.html")


@app.route("/room/create", methods=["POST"])
def create_room_submit():
    host_name            = request.form.get("host_name", "").strip()
    title                = request.form.get("title", "").strip()
    max_participants_raw = request.form.get("max_participants", "").strip()
    spp_raw              = request.form.get("suggestions_per_person", "").strip()
    # Get the selected voting method from the radio buttons
    voting_method        = request.form.get("voting_method", "borda")
    res_anon = request.form.get("results_anonymous") == "on"

    host_lat = host_lng = None
    raw_lat  = request.form.get("host_lat", "").strip()
    raw_lng  = request.form.get("host_lng", "").strip()
    if raw_lat and raw_lng:
        try:
            host_lat = float(raw_lat)
            host_lng = float(raw_lng)
            if not (-90 <= host_lat <= 90) or not (-180 <= host_lng <= 180):
                host_lat = host_lng = None
        except ValueError:
            host_lat = host_lng = None

    errors = []
    if not host_name:
        errors.append("Your name is required.")
    if not title:
        errors.append("A room title is required.")

    max_participants = None
    try:
        max_participants = int(max_participants_raw)
        if max_participants < 2:
            errors.append("Max participants must be at least 2.")
            max_participants = None
    except ValueError:
        errors.append("Max participants must be a whole number.")

    suggestions_per_person = None
    try:
        suggestions_per_person = int(spp_raw)
        if suggestions_per_person < 1:
            errors.append("Suggestions per person must be at least 1.")
            suggestions_per_person = None
    except ValueError:
        errors.append("Suggestions per person must be a whole number.")

    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("create_room.html", form_data=request.form), 422

    try:
        room = create_room(
            host_name=host_name,
            title=title,
            max_participants=max_participants,
            suggestions_per_person=suggestions_per_person,
            results_anonymous=res_anon,
            voting_method=voting_method,
            host_lat=host_lat,
            host_lng=host_lng,
        )
    except (ValueError, RuntimeError) as e:
        flash(str(e), "error")
        return render_template("create_room.html", form_data=request.form), 500

    session["room_code"]    = room["room_code"]
    session["room_id"]      = room["id"]
    session["display_name"] = host_name
    session["is_host"]      = True

    return redirect(url_for("lobby", code=room["room_code"]))


# ---------------------------------------------------------------------------
# Join room
# ---------------------------------------------------------------------------

@app.route("/join", methods=["GET"])
def join_room_page():
    prefill_code = request.args.get("code", "").upper().strip()
    return render_template("join_room.html", prefill_code=prefill_code)


@app.route("/join", methods=["POST"])
def join_room_submit():
    room_code    = request.form.get("room_code", "").upper().strip()
    display_name = request.form.get("display_name", "").strip()

    errors = []
    if not room_code:
        errors.append("A room code is required.")
    if not display_name:
        errors.append("Your name is required.")

    if errors:
        for e in errors:
            flash(e, "error")
        return render_template(
            "join_room.html", prefill_code=room_code, form_data=request.form
        ), 422

    room = get_room_by_code(room_code)
    if not room:
        flash("No room found with that code. Double-check and try again.", "error")
        return render_template(
            "join_room.html", prefill_code=room_code, form_data=request.form
        ), 404

    # Reject duplicate names outright
    existing_participants = get_participants(room["id"])
    name_taken = any(
        p["display_name"].lower() == display_name.lower()
        for p in existing_participants
    )
    if name_taken:
        flash("That name is already in use in this room. Please choose a different name.", "error")
        return render_template(
            "join_room.html", prefill_code=room_code, form_data=request.form
        ), 400

    try:
        add_participant(room_id=room["id"], display_name=display_name)
    except ValueError as e:
        flash(str(e), "error")
        return render_template(
            "join_room.html", prefill_code=room_code, form_data=request.form
        ), 400

    session["room_code"]    = room["room_code"]
    session["room_id"]      = room["id"]
    session["display_name"] = display_name
    session["is_host"]      = False

    return redirect(url_for("lobby", code=room["room_code"]))


# ---------------------------------------------------------------------------
# Lobby
# ---------------------------------------------------------------------------

@app.route("/room/<code>/lobby")
def lobby(code: str):
    room = get_room_by_code(code)
    if not room:
        flash("That room doesn't exist.", "error")
        return redirect(url_for("home"))

    # Skip lobby if room already started
    if room["phase"] != "lobby":
        return redirect(url_for("suggestions_page", code=code))

    display_name, is_host = _require_session(code)
    if display_name is None:
        return redirect(url_for("join_room_page", code=code))

    participants = get_participants(room["id"])
    my_participant = next(
        (p for p in participants if p["display_name"] == display_name), {}
    )
    return render_template(
        "lobby.html",
        room=room,
        participants=participants,
        display_name=display_name,
        is_host=is_host,
        my_avatar=my_participant.get("avatar"),
        voting_method_label=VOTING_METHODS.get(
            room.get("voting_method", "borda"), "Borda Count"
        ),
    )


# ---------------------------------------------------------------------------
# Start suggestions  (host only, POST)
# ---------------------------------------------------------------------------

@app.route("/room/<code>/start", methods=["POST"])
def start_suggestions(code: str):
    if not session.get("is_host") or session.get("room_code") != code:
        flash("Only the host can start suggestions.", "error")
        return redirect(url_for("lobby", code=code))

    room = get_room_by_code(code)
    if not room:
        flash("Room not found.", "error")
        return redirect(url_for("home"))

    if room["phase"] != "lobby":
        return redirect(url_for("suggestions_page", code=code))

    try:
        update_phase(room["id"], "suggesting")
    except (ValueError, RuntimeError) as e:
        flash(str(e), "error")
        return redirect(url_for("lobby", code=code))

    return redirect(url_for("suggestions_page", code=code))


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

@app.route("/room/<code>/suggestions", methods=["GET"])
def suggestions_page(code: str):
    room = get_room_by_code(code)
    if not room:
        flash("That room doesn't exist.", "error")
        return redirect(url_for("home"))

    display_name, is_host = _require_session(code)
    if display_name is None:
        return redirect(url_for("join_room_page", code=code))

    # Phase guards — redirect to the right page
    if room["phase"] == "lobby":
        return redirect(url_for("lobby", code=code))
    if room["phase"] == "voting":
        return redirect(url_for("voting_page", code=code))
    if room["phase"] == "results":
        return redirect(url_for("results_page", code=code))

    my_suggestions  = get_suggestions_by_participant(room["id"], display_name)
    all_suggestions = get_suggestions(room["id"])
    slots_used      = len(my_suggestions)
    slots_total     = room["suggestions_per_person"]
    slots_remaining = max(0, slots_total - slots_used)

    participants = get_participants(room["id"])
    done_participants = get_done_participants(room["id"])
    suggestions_done = display_name in done_participants
    return render_template(
        "suggestions.html",
        room=room,
        display_name=display_name,
        is_host=is_host,
        my_suggestions=my_suggestions,
        all_suggestions=all_suggestions,
        slots_used=slots_used,
        slots_total=slots_total,
        slots_remaining=slots_remaining,
        participants=participants,
        suggestions_done=suggestions_done,
        phase_deadline=_phase_deadline(room),
        server_now=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/room/<code>/set-avatar", methods=["POST"])
def set_avatar_route(code: str):
    display_name, _ = _require_session(code)
    if display_name is None:
        return jsonify({"error": "Not in session."}), 401

    room = get_room_by_code(code)
    if not room:
        return jsonify({"error": "Room not found."}), 404

    avatar = request.json.get("avatar", "").strip()
    if not avatar:
        return jsonify({"error": "No avatar provided."}), 400

    # Only allow expected filenames
    allowed = {f"avatar_{i}.png" for i in range(1, 13)}
    if avatar not in allowed:
        return jsonify({"error": "Invalid avatar."}), 400

    try:
        set_avatar(room["id"], display_name, avatar)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "avatar": avatar})


@app.route("/room/<code>/suggestions", methods=["POST"])
def suggestions_submit(code: str):
    display_name, _ = _require_session(code)
    if display_name is None:
        return redirect(url_for("join_room_page", code=code))

    room = get_room_by_code(code)
    if not room:
        flash("Room not found.", "error")
        return redirect(url_for("home"))

    text = request.form.get("suggestion_text", "").strip()
    if not text:
        flash("Suggestion cannot be blank.", "error")
        return redirect(url_for("suggestions_page", code=code))

    if profanity.contains_profanity(text):
        flash("Your suggestion contains inappropriate language. Please revise it.", "error")
        return redirect(url_for("suggestions_page", code=code))

    try:
        add_suggestion(room_id=room["id"], participant_name=display_name, text=text)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("suggestions_page", code=code))

    # Auto-advance if this was the last submission needed
    participants = get_participants(room["id"])
    if has_everyone_suggested(room["id"], participants, room["suggestions_per_person"]):
        try:
            update_phase(room["id"], "voting")
        except (ValueError, RuntimeError):
            pass  # poll will catch it
        return redirect(url_for("voting_page", code=code))

    return redirect(url_for("suggestions_page", code=code))


@app.route("/room/<code>/suggestions/done", methods=["POST"])
def suggestions_done_route(code: str):
    display_name, _ = _require_session(code)
    if display_name is None:
        return redirect(url_for("join_room_page", code=code))

    room = get_room_by_code(code)
    if not room or room["phase"] != "suggesting":
        return redirect(url_for("suggestions_page", code=code))

    my_suggestions = get_suggestions_by_participant(room["id"], display_name)
    if len(my_suggestions) < 1:
        flash("You must add at least one suggestion before finishing early.", "error")
        return redirect(url_for("suggestions_page", code=code))

    mark_suggestions_done(room["id"], display_name)

    participants = get_participants(room["id"])
    if has_everyone_suggested(room["id"], participants, room["suggestions_per_person"]):
        try:
            update_phase(room["id"], "voting")
        except (ValueError, RuntimeError):
            pass
        return redirect(url_for("voting_page", code=code))

    return redirect(url_for("suggestions_page", code=code))


# ---------------------------------------------------------------------------
# Start voting  (host only, POST)
# ---------------------------------------------------------------------------

@app.route("/room/<code>/start-voting", methods=["POST"])
def start_voting(code: str):
    if not session.get("is_host") or session.get("room_code") != code:
        flash("Only the host can start voting.", "error")
        return redirect(url_for("suggestions_page", code=code))

    room = get_room_by_code(code)
    if not room:
        flash("Room not found.", "error")
        return redirect(url_for("home"))

    suggestions = get_suggestions(room["id"])
    if len(suggestions) < 2:
        flash("You need at least 2 suggestions before voting can begin.", "error")
        return redirect(url_for("suggestions_page", code=code))

    if room["phase"] != "suggesting":
        return redirect(url_for("voting_page", code=code))

    try:
        update_phase(room["id"], "voting")
    except (ValueError, RuntimeError) as e:
        flash(str(e), "error")
        return redirect(url_for("suggestions_page", code=code))

    return redirect(url_for("voting_page", code=code))


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------

@app.route("/room/<code>/voting", methods=["GET"])
def voting_page(code: str):
    room = get_room_by_code(code)
    if not room:
        flash("That room doesn't exist.", "error")
        return redirect(url_for("home"))

    display_name, is_host = _require_session(code)
    if display_name is None:
        return redirect(url_for("join_room_page", code=code))

    # Phase guards
    if room["phase"] == "lobby":
        return redirect(url_for("lobby", code=code))
    if room["phase"] == "suggesting":
        return redirect(url_for("suggestions_page", code=code))
    if room["phase"] == "results":
        return redirect(url_for("results_page", code=code))

    suggestions     = get_suggestions(room["id"])
    participants    = get_participants(room["id"])
    voters          = get_voters(room["id"])
    my_vote         = get_vote_by_participant(room["id"], display_name)
    has_voted       = len(my_vote) > 0

    # Build the ordered suggestion list for this participant:
    # If they've already voted, show their saved order; otherwise default order.
    if has_voted:
        voted_ids = [v["suggestion_id"] for v in my_vote]  # rank-ordered
        by_id     = {s["id"]: s for s in suggestions}
        ordered   = [by_id[sid] for sid in voted_ids if sid in by_id]
        # Append any suggestions that weren't in their vote (edge case)
        voted_set = set(voted_ids)
        ordered  += [s for s in suggestions if s["id"] not in voted_set]
    else:
        ordered = suggestions

    return render_template(
        "voting.html",
        room=room,
        display_name=display_name,
        is_host=is_host,
        suggestions=ordered,
        voters=voters,
        participants=participants,
        has_voted=has_voted,
        voters_count=len(voters),
        participants_count=len(participants),
        phase_deadline=_phase_deadline(room),
        server_now=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/room/<code>/voting", methods=["POST"])
def voting_submit(code: str):
    display_name, _ = _require_session(code)
    if display_name is None:
        return redirect(url_for("join_room_page", code=code))

    room = get_room_by_code(code)
    if not room:
        flash("Room not found.", "error")
        return redirect(url_for("home"))

    # Parse the comma-separated ranked suggestion IDs from the hidden input
    raw = request.form.get("ranked_ids", "").strip()
    if not raw:
        flash("Please rank the suggestions before submitting.", "error")
        return redirect(url_for("voting_page", code=code))

    ranked_ids = [s.strip() for s in raw.split(",") if s.strip()]

    try:
        save_vote(
            room_id=room["id"],
            participant_name=display_name,
            ranked_suggestion_ids=ranked_ids,
        )
    except (ValueError, RuntimeError) as e:
        flash(str(e), "error")
        return redirect(url_for("voting_page", code=code))

    # Auto-advance to results if everyone has now voted
    participants = get_participants(room["id"])
    if has_everyone_voted(room["id"], participants):
        try:
            update_phase(room["id"], "results")
        except (ValueError, RuntimeError):
            pass  # Non-fatal — results page will still work
        return redirect(url_for("results_page", code=code))

    flash("Vote submitted! You can update it any time before voting closes.", "success")
    return redirect(url_for("voting_page", code=code))


# ---------------------------------------------------------------------------
# Force results  (host only, POST)
# ---------------------------------------------------------------------------

@app.route("/room/<code>/force-results", methods=["POST"])
def force_results(code: str):
    if not session.get("is_host") or session.get("room_code") != code:
        flash("Only the host can do this.", "error")
        return redirect(url_for("voting_page", code=code))

    room = get_room_by_code(code)
    if not room:
        flash("Room not found.", "error")
        return redirect(url_for("home"))

    try:
        update_phase(room["id"], "results")
    except (ValueError, RuntimeError) as e:
        flash(str(e), "error")
        return redirect(url_for("voting_page", code=code))

    return redirect(url_for("results_page", code=code))


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@app.route("/room/<code>/results")
def results_page(code: str):
    room = get_room_by_code(code)
    if not room:
        flash("That room doesn't exist.", "error")
        return redirect(url_for("home"))

    display_name, is_host = _require_session(code)
    if display_name is None:
        return redirect(url_for("join_room_page", code=code))

    # Explicitly get the voting method to ensure the template receives it
    voting_method = room.get("voting_method", "borda")

    suggestions = get_suggestions(room["id"])
    results     = calculate_results(room["id"], suggestions)
    voters      = get_voters(room["id"])
    participants = get_participants(room["id"])

    return render_template(
        "results.html",
        room=room,
        display_name=display_name,
        is_host=is_host,
        results=results,
        voters_count=len(voters),
        participants_count=len(participants),
        voting_method=voting_method,
    )


# ---------------------------------------------------------------------------
# API — room status  (polled by lobby, suggestions, and voting pages)
# ---------------------------------------------------------------------------

@app.route("/api/room/<code>/participants")
def api_participants(code: str):
    """
    Return room phase, participants, and voter count as JSON.

    Response shape:
        {
            "phase":            "lobby" | "suggesting" | "voting" | "results",
            "participants":     [ { "display_name": "...", ... }, ... ],
            "voters_count":     3,
            "participants_count": 5
        }
    """
    room = get_room_by_code(code)
    if not room:
        return jsonify({"error": "Room not found."}), 404

    # AFTER
    participants    = get_participants(room["id"])
    voters          = get_voters(room["id"]) if room["phase"] == "voting" else []
    all_suggestions = get_suggestions(room["id"]) if room["phase"] == "suggesting" else []

    current_phase  = room["phase"]
    phase_deadline = _phase_deadline(room)
    timer_expired  = (
        phase_deadline is not None
        and datetime.now(timezone.utc) >= datetime.fromisoformat(phase_deadline)
    )

    # Auto-advance to voting if everyone submitted or timer expired
    if current_phase == "suggesting" and (
        timer_expired or has_everyone_suggested(room["id"], participants, room["suggestions_per_person"])
    ):
        try:
            update_phase(room["id"], "voting")
            current_phase  = "voting"
            phase_deadline = None
            timer_expired  = False
        except (ValueError, RuntimeError):
            pass

    # Auto-advance to results if everyone voted or timer expired
    if current_phase == "voting" and (
        timer_expired or has_everyone_voted(room["id"], participants)
    ):
        try:
            update_phase(room["id"], "results")
            current_phase  = "results"
            phase_deadline = None
        except (ValueError, RuntimeError):
            pass

    # Expire lobby rooms where only the host is present after 10 minutes
    if current_phase == "lobby" and len(participants) == 1:
        created_at_str = room.get("created_at", "")
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) - created_at > timedelta(minutes=10):
                    update_phase(room["id"], "expired")
                    current_phase = "expired"
            except (ValueError, RuntimeError):
                pass

    return jsonify({
        "phase":              current_phase,
        "participants":       participants,
        "voters_count":       len(voters),
        "participants_count": len(participants),
        "all_suggestions":    all_suggestions,
        "voting_method":      room.get("voting_method", "borda"),
        "results_anonymous":  room.get("results_anonymous", True),
        "phase_deadline":     phase_deadline,
        "server_now":         datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# API — AI description for a single suggestion (lazy-loaded, cached in DB)
# ---------------------------------------------------------------------------

@app.route("/api/room/<code>/suggestion/<suggestion_id>/describe")
def api_describe_suggestion(code: str, suggestion_id: str):
    room = get_room_by_code(code)
    if not room:
        return jsonify({"error": "Room not found."}), 404

    suggestion = get_suggestion_by_id(suggestion_id)
    if not suggestion:
        return jsonify({"error": "Suggestion not found."}), 404

    if suggestion["room_id"] != room["id"]:
        return jsonify({"error": "Suggestion does not belong to this room."}), 409

    # Cache hit — already generated
    if suggestion.get("ai_description"):
        return jsonify({"description": suggestion["ai_description"]})

    # Generate via Gemini
    try:
        description = generate_suggestion_description(room["title"], suggestion["text"])
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    # Persist (non-fatal if it fails)
    try:
        save_ai_description(suggestion_id, description)
    except Exception:
        pass

    return jsonify({"description": description})


@app.route("/api/nearby-rooms")
def api_nearby_rooms():
    """
    GET /api/nearby-rooms?lat=<float>&lng=<float>
    Returns lobby-phase rooms whose host is within 1 km of the given coordinates.
    """
    raw_lat = request.args.get("lat", "").strip()
    raw_lng = request.args.get("lng", "").strip()

    if not raw_lat or not raw_lng:
        return jsonify({"error": "lat and lng query parameters are required."}), 400

    try:
        lat = float(raw_lat)
        lng = float(raw_lng)
    except ValueError:
        return jsonify({"error": "lat and lng must be valid numbers."}), 400

    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return jsonify({"error": "Coordinates out of valid range."}), 400

    return jsonify({"rooms": get_nearby_rooms(lat, lng)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)