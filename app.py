# app.py
import json
import uuid
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

# --------------------------------------------------------------
# In‑memory stores
# --------------------------------------------------------------
# token -> {"session_id": str, "user_id": str}
sessions = {}

# user_id -> dict with user‑config fields (appearanceId, basePersonaId, jingle, rollingPoints, ...)
users = {}

# game_id -> {
#     "config": dict,               # from GameSessionCreateRequest / SetGameInfo
#     "users": set of user_id,      # players presently in the session
#     "reservations": int,          # from /reservation endpoint
#     "scores": dict round_id -> list of {lapData, raceTimeData}
# }
games = {}

# leaderboard_name -> list of entries (each entry is a dict)
leaderboards = {}

# simple static data for newsfeed, tournaments, challenges, stats
newsfeed_items = [
    {
        "id": 1,
        "title": "Welcome to NASCAR Heat 5",
        "body": "Enjoy the races!",
        "timestamp": 0,
        "type": 0,
        "imageUrl": "",
        "linkUrl": ""
    }
]

tournament_events = []   # list of TRNEventInfoResponse objects
tournament_history = []  # list of TRNHistory objects (we just store raw dicts)

challenges = []          # list of challenge dicts (filled lazily if needed)

stats_values = {}        # category -> dict of values

# --------------------------------------------------------------
# Helper functions
# --------------------------------------------------------------
def make_token():
    """Generate a unique bearer token."""
    return str(uuid.uuid4())

def make_session_id():
    return str(uuid.uuid4())

def make_user_id():
    return str(uuid.uuid4())

def make_game_id():
    return f"game_{len(games) + 1}"

def json_response(data, status=200):
    """Utility to always return proper JSON + content‑type."""
    resp = jsonify(data)
    resp.status_code = status
    resp.headers["Content-Type"] = "application/json"
    return resp

def require_auth():
    """Validate MGI-Bearer-Token header; abort with 401 if missing/invalid."""
    token = request.headers.get("MGI-Bearer-Token")
    if token not in sessions:
        abort(401, description="Invalid or missing token")
    return sessions[token]   # return the session dict (has user_id)

# --------------------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------------------
@app.route("/user", methods=["POST"])
def create_user():
    """
    Request: UserSessionCreateRequest
    {
        "platform": "...",
        "auth_token": "...",   # ignored for emulator
        "version": "...",
        "client_version": "..."
    }
    Response: UserSessionCreateResponse
    {
        "session_id": "...",
        "mgi_token": "..."
    }
    """
    _ = request.get_json(silent=True) or {}   # we don't need to store the request fields
    user_id = make_user_id()
    token = make_token()
    session_id = make_session_id()
    # create a placeholder user entry (will be filled via /user/config)
    users[user_id] = {
        "userId": user_id,
        "isLocalUser": True,   # the locally logged‑in user
        "mpIdx": 0,
        "name": "Player",
        "platformUserId": "",
        "sortVal": 0.0,
        "isVerified": False,
        "basePersonaId": "",
        "appearanceId": "",
        "jingle": "",
        "rollingPoints": 0,
        "badge": None
    }
    sessions[token] = {"session_id": session_id, "user_id": user_id}
    return json_response({"session_id": session_id, "mgi_token": token})

@app.route("/auth", methods=["GET"])
def auth():
    """
    The game sends MGI-Bearer-Token; we just need to return 200 with an empty JSON object.
    """
    token = request.headers.get("MGI-Bearer-Token")
    if token not in sessions:
        abort(401, description="Invalid token")
    # EmptyResponse = {}
    return json_response({})

# --------------------------------------------------------------
# BROWSE / SESSION LISTING
# --------------------------------------------------------------
@app.route("/game", methods=["GET"])
def browse():
    """
    Query: start_idx, max_results, category, val (multiple – keys the client wants)
    Response: BrowseResponse { "games": [ { GameSessionInfo ... } ] }
    """
    start = int(request.args.get("start_idx", 0))
    max_results = int(request.args.get("max_results", 20))
    # category and val are ignored for simplicity – we still return a sensible GameSessionInfo
    # based on each game's stored config.
    game_list = []
    for gid, g in list(games.items())[start:start+max_results]:
        info = build_game_session_info(gid, g)
        game_list.append(info)
    return json_response({"games": game_list})

@app.route("/game/<game_id>", methods=["GET"])
def game_info(game_id):
    """
    Response: same as a single element inside BrowseResponse.games (wrapped in a "games" list).
    """
    if game_id not in games:
        abort(404, description="Game not found")
    info = build_game_session_info(game_id, games[game_id])
    return json_response({"games": [info]})

@app.route("/game/<game_id>/round/<round_id>", methods=["GET"])
def round_info(game_id, round_id):
    """
    The round‑info endpoint returns the same structure as a normal game info,
    but with the roundId field set to the requested round_id.
    """
    if game_id not in games:
        abort(404, description="Game not found")
    info = build_game_session_info(game_id, games[game_id])
    # Overwrite the roundId to the requested one (the game checks this)
    info["roundId"] = round_id
    return json_response({"games": [info]})

def build_game_session_info(game_id, game_data):
    """
    Construct a GameSessionInfo‑compatible dict from stored game data.
    Only the fields that the client actually reads before joining are filled;
    missing fields are given sensible defaults.
    """
    config = game_data.get("config", {})
    # Default values – can be overridden by config keys that match the names the game sends.
    info = {
        "id": game_id,
        "srv": {
            "users": len(game_data.get("users", set())),
            "cap": config.get("capacity", 2)
        },
        "fields": [],  # the actual field parsing is done by the client using the key list; we leave it empty.
        # Basic boolean / enum fields (ints matching the C# enums)
        "enableAI": config.get("enableAI", False),
        "enableChat": config.get("enableChat", False),
        "numLaps": config.get("numLaps", 0),
        "league": config.get("league", 0),               # 0 = CUP
        "flags": config.get("flags", 0),
        "stageCfg": config.get("stageCfg", ""),
        "state": "lobby",
        "friendlyState": "Lobby",
        "roundId": "",                                   # will be overridden by /round/<id> endpoint
        "stateTimeout": 0,
        "raceLength": 0,
        "wearFactor": 0,
        "draftInfluence": 0,
        "eventId": "",                                   # empty = default EventId
        "eventSetId": "",
        "sessionType": 0,                                # 0 = PRIVATE (from NetGameSessionType)
        "gameYear": 0,
        "friendlyTrackName": config.get("friendlyTrackName", ""),
        "damage": config.get("damage", 0),
        "purpose": "",
        "liveDataInterval": 0,
        "isProMode": False,
        "minUsersForScoring": 0,
        "trnclass": 0,
        # String fields often accessed:
        "platformSessionId": "",
        "platformCorrelationId": "",
        "masterUserId": "",
        "masterName": "",
        "masterIsVerified": False,
        "isPrivate": config.get("isPrivate", False),
        "forceSimPhysics": config.get("forceSimPhysics", False),
        "allowCustomSetups": config.get("allowCustomSetups", False)
    }
    return info

# --------------------------------------------------------------
# SESSION MANAGEMENT
# --------------------------------------------------------------
@app.route("/game/<game_id>/reservation", methods=["POST"])
def reserve_slots(game_id):
    """
    Request: ReservationRequest { "count": <int> }
    Response: ReservationResponse (empty – just 200)
    """
    if game_id not in games:
        abort(404, description="Game not found")
    data = request.get_json(silent=True) or {}
    games[game_id]["reservations"] = data.get("count", 0)
    return json_response({})

@app.route("/game", methods=["POST"])
def create_game():
    """
    Request: GameSessionCreateRequest
    {
        "backend": {...},
        "config": {...},
        "category": "...",
        "tid": {...}
    }
    Response: GameSessionCreateResponse { "id": "<new‑game‑id>" }
    """
    data = request.get_json(silent=True) or {}
    # We don't validate backend/tid for the emulator, just keep the config.
    gid = make_game_id()
    games[gid] = {
        "config": data.get("config", {}),
        "users": set(),
        "reservations": 0,
        "scores": {}          # round_id -> list of score events
    }
    return json_response({"id": gid})

@app.route("/game/<game_id>/add_user", methods=["POST"])
def add_user(game_id):
    """
    Request: JoinRequest { "reservation": "...", "trn_user_subgroup": "..." }
    Response: JoinResponse (empty)
    The user making the request is identified by the MGI-Bearer-Token header.
    """
    sess = require_auth()               # validates token and returns session dict
    user_id = sess["user_id"]
    if game_id not in games:
        abort(404, description="Game not found")
    games[game_id]["users"].add(user_id)
    return json_response({})

@app.route("/game/<game_id>", methods=["POST"])
def set_game_info(game_id):
    """
    Request: GameSessionConfigRequest { "config": {...} }
    Response: EmptyResponse
    """
    if game_id not in games:
        abort(404, description="Game not found")
    data = request.get_json(silent=True) or {}
    # Merge the incoming config with existing (overwrite)
    games[game_id]["config"].update(data.get("config", {}))
    return json_response({})

@app.route("/game/<game_id>/op/<op>", methods=["POST"])
def game_op(game_id, op):
    """
    Request: EmptyRequest
    Response: OperationResponse (empty)
    """
    # No state change needed for the emulator
    return json_response({})

@app.route("/game/<game_id>/del_user", methods=["POST"])
def remove_user(game_id):
    """
    Request: LeaveRequest { "reason": "..." }
    Response: EmptyResponse
    The user leaving is the one identified by the auth token.
    """
    sess = require_auth()
    user_id = sess["user_id"]
    if game_id in games:
        games[game_id]["users"].discard(user_id)
    return json_response({})

@app.route("/game/<game_id>/del_user/<user_id>", methods=["POST"])
def kick_user(game_id, user_id):
    """
    Request: EmptyRequest
    Response: EmptyResponse
    """
    if game_id not in games:
        abort(404, description="Game not found")
    games[game_id]["users"].discard(user_id)
    return json_response({})

# --------------------------------------------------------------
# PLAYER INFO
# --------------------------------------------------------------
@app.route("/game/<game_id>/round/<round_id>/participants", methods=["GET"])
def participants(game_id, round_id):
    """
    Response: UserSessionInfoList { "users": [ { UserSessionInfo ... } ] }
    """
    if game_id not in games:
        abort(404, description="Game not found")
    sess = require_auth()   # we need the token to know which user is local
    local_user_id = sess["user_id"]
    user_list = []
    for idx, uid in enumerate(games[game_id]["users"]):
        u = users.get(uid, {})
        # Build a UserSessionInfo‑compatible dict
        user_info = {
            "userId": uid,
            "isLocalUser": (uid == local_user_id),
            "mpIdx": idx,
            "name": u.get("name", "Player"),
            "platformUserId": u.get("platformUserId", ""),
            "sortVal": float(u.get("sortVal", 0.0)),
            "isVerified": u.get("isVerified", False),
            "basePersonaId": u.get("basePersonaId", ""),
            "appearanceId": u.get("appearanceId", ""),
            "jingle": u.get("jingle", ""),
            "rollingPoints": int(u.get("rollingPoints", 0)),
            "badge": u.get("badge", None)
        }
        user_list.append(user_info)
    return json_response({"users": user_list})

@app.route("/game/<game_id>/users", methods=["GET"])
def users_in_game(game_id):
    """
    Same as participants but without round context – we just reuse the same logic.
    """
    return participants(game_id, "0")   # round_id is irrelevant for this endpoint

@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    """
    Response: UserSessionInfo (many fields – we return what we have stored).
    """
    if user_id not in users:
        abort(404, description="User not found")
    u = users[user_id]
    # Ensure we return all expected fields with sensible defaults
    resp = {
        "userId": u.get("userId", user_id),
        "isLocalUser": u.get("isLocalUser", False),
        "mpIdx": u.get("mpIdx", 0),
        "name": u.get("name", "Player"),
        "platformUserId": u.get("platformUserId", ""),
        "sortVal": float(u.get("sortVal", 0.0)),
        "isVerified": u.get("isVerified", False),
        "basePersonaId": u.get("basePersonaId", ""),
        "appearanceId": u.get("appearanceId", ""),
        "jingle": u.get("jingle", ""),
        "rollingPoints": int(u.get("rollingPoints", 0)),
        "badge": u.get("badge", None)
    }
    return json_response(resp)

@app.route("/user/config", methods=["POST"])
def set_user_info():
    """
    Request: UserSessionConfigRequest { "config": {...} }
    Response: EmptyResponse
    The config contains the fields the game sends when setting up a local user.
    """
    sess = require_auth()
    user_id = sess["user_id"]
    data = request.get_json(silent=True) or {}
    cfg = data.get("config", {})
    # Update the stored user dict with whatever fields the client sent.
    # We keep the existing keys and just overlay the new values.
    if user_id in users:
        users[user_id].update(cfg)
    else:
        # If for some reason the user didn't exist, create a minimal entry.
        users[user_id] = {
            "userId": user_id,
            "isLocalUser": True,
            "mpIdx": 0,
            "name": "Player",
            "platformUserId": "",
            "sortVal": 0.0,
            "isVerified": False,
            "basePersonaId": "",
            "appearanceId": "",
            "jingle": "",
            "rollingPoints": 0,
            "badge": None
        }
        users[user_id].update(cfg)
    return json_response({})

# --------------------------------------------------------------
# GAMEPLAY EVENTS (lap / race scores)
# --------------------------------------------------------------
@app.route("/game/<game_id>/round/<round_id>/score", methods=["POST"])
def post_score_event(game_id, round_id):
    """
    Request: GameSessionScoreEvent (may contain LapData or RaceTimeData)
    Response: EmptyResponse
    We store the event so it can be queried later if the client ever asks for it.
    """
    if game_id not in games:
        abort(404, description="Game not found")
    data = request.get_json(silent=True) or {}
    event = {
        "lapData": data.get("data"),          # LapData object or None
        "raceTimeData": data.get("racetime_data")  # RaceTimeData object or None
    }
    games[game_id]["scores"].setdefault(round_id, []).append(event)
    return json_response({})

# --------------------------------------------------------------
# INVITATIONS
# --------------------------------------------------------------
@app.route("/invitation/consume", methods=["POST"])
def consume_invitation():
    """
    Request: ConsumeInvitationRequest { "invitationId": "..." }
    Response: EmptyResponse
    """
    _ = request.get_json(silent=True) or {}
    return json_response({})

@app.route("/invitation/send", methods=["POST"])
def invite_bunch():
    """
    Request: MultipleInviteRequest { "platformSessionId": "...", "platformUserIds": [...] }
    Response: EmptyResponse
    """
    _ = request.get_json(silent=True) or {}
    return json_response({})

# --------------------------------------------------------------
# TELEMETRY
# --------------------------------------------------------------
@app.route("/info/connection", methods=["POST"])
def report_connection():
    """
    Request: ConnectionInfoMessage
    Response: EmptyResponse
    """
    _ = request.get_json(silent=True) or {}
    return json_response({})

# --------------------------------------------------------------
# NEWS FEED
# --------------------------------------------------------------
@app.route("/newsfeed/list", methods=["GET"])
def newsfeed_list():
    """
    Response: NewsfeedListResponse { "items": [ { NewsfeedItemResponse ... } ] }
    """
    return json_response({"items": newsfeed_items})

@app.route("/newsfeed/<int:item_id>", methods=["GET"])
def newsfeed_item(item_id):
    """
    Response: NewsfeedItemResponse
    """
    for item in newsfeed_items:
        if item["id"] == item_id:
            return json_response(item)
    abort(404, description="Newsfeed item not found")

# --------------------------------------------------------------
# ANALYTICS
# --------------------------------------------------------------
@app.route("/analytics/postrace", methods=["POST"])
def post_race_analytics():
    """
    Request: PostRaceAnalyticsData
    Response: EmptyResponse
    """
    _ = request.get_json(silent=True) or {}
    return json_response({})

# --------------------------------------------------------------
# LEADERBOARDS
# --------------------------------------------------------------
@app.route("/leaderboard/<lb_name>/<kind>", methods=["GET"])
def leaderboard_query(lb_name, kind):
    """
    Query: start_at, count
    Response: LeaderboardQueryResponse { "entries": [...], "total": <int> }
    """
    start = int(request.args.get("start_at", 0))
    cnt = int(request.args.get("count", 0))
    entries = leaderboards.get(lb_name, [])
    sliced = entries[start:start+cnt]
    return json_response({"entries": sliced, "total": len(entries)})

@app.route("/leaderboard", methods=["POST"])
def leaderboard_post():
    """
    Request: LeaderboardPostRequest { "posts": [LeaderboardPost, ...] }
    Response: LeaderboardQueryResponse (same shape as GET)
    """
    data = request.get_json(silent=True) or {}
    posts = data.get("posts", [])
    # For simplicity we treat each post as a leaderboard entry and append to a generic leaderboard.
    # In a real implementation you would look at the post's leaderboard name.
    lb_name = "global"
    leaderboards.setdefault(lb_name, []).extend(posts)
    return json_response({"entries": leaderboards[lb_name][-len(posts):], "total": len(leaderboards[lb_name])})

@app.route("/leaderboard/advance_time", methods=["POST"])
def advance_leaderboard_time():
    """
    Request: LeaderboardAdvanceTimeRequest { "names": [...] }
    Response: LeaderboardQueryResponse
    """
    _ = request.get_json(silent=True) or {}
    # No-op for the emulator; just return an empty list.
    return json_response({"entries": [], "total": 0})

# --------------------------------------------------------------
# STATS
# --------------------------------------------------------------
@app.route("/stats", methods=["GET"])
def get_stats():
    """
    Query: category
    Response: StatsResponse { "values": { ... } }
    """
    category = request.args.get("category", "")
    return json_response({"values": stats_values.get(category, {})})

# --------------------------------------------------------------
# TOURNAMENT
# --------------------------------------------------------------
@app.route("/tournament/event_info/<adv>/<subgroup>", methods=["GET"])
def tournament_event_info(adv, subgroup):
    """
    Response: TRNEventInfoResponse
    """
    # Return static dummy data; could be made dynamic if needed.
    dummy = {
        "eventId": "",
        "name": "Test Event",
        "description": "",
        "startTime": 0,
        "endTime": 0,
        "isActive": False,
        "reward": "",
        "icon": ""
    }
    return json_response(dummy)

@app.route("/tournament/history/<adv>/<subgroup>", methods=["GET"])
def tournament_history(adv, subgroup):
    """
    Response: TRNHistory (we just return an empty list – the wrapper expects a list)
    """
    return json_response([])

# --------------------------------------------------------------
# CHALLENGES
# --------------------------------------------------------------
@app.route("/challenge/list", methods=["GET"])
def challenge_list():
    """
    Query: limit, published, full
    Response: ChallengeListResponse { "challenges": [...] }
    """
    return json_response({"challenges": challenges})

@app.route("/challenge/leaderboard/<assists_level>", methods=["GET"])
def challenge_leaderboard(assists_level):
    """
    Response: ChallengeLeaderboardResponse { "entries": [...] }
    """
    return json_response({"entries": []})

@app.route("/challenge/completed/<challenge_id>", methods=["POST"])
def post_challenge_leaderboard(challenge_id):
    """
    Request: ChallengeLeaderboardPostRequest { "score": <float> }
    Response: ChallengeLeaderboardResponse
    """
    _ = request.get_json(silent=True) or {}
    return json_response({"entries": []})

# --------------------------------------------------------------
# RUN
# --------------------------------------------------------------
if __name__ == "__main__":
    # Enable debug logging so you can see request/response details while testing.
    app.logger.setLevel("DEBUG")
    app.run(host="0.0.0.0", port=8000, debug=True)