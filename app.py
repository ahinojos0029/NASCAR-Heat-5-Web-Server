# app.py
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

# ----------------------------------------------------------------------
# In‑memory stores – enough for the emulator to work
# ----------------------------------------------------------------------
sessions = {}          # token -> session_id
game_sessions = {}     # game_id -> dict with config, users, etc.
users = {}             # user_id -> dict with user info

# ----------------------------------------------------------------------
# Helper to always return JSON with correct content‑type
# ----------------------------------------------------------------------
def json_response(data, status=200):
    resp = jsonify(data)
    resp.status_code = status
    resp.headers["Content-Type"] = "application/json"
    return resp

# ----------------------------------------------------------------------
# AUTHENTICATION
# ----------------------------------------------------------------------
@app.route("/user", methods=["POST"])
def create_user():
    """
    Expected request JSON (as seen in UserSessionCreateRequest):
    {
        "platform": "...",
        "auth_token": "...",
        "version": "...",
        "client_version": "..."
    }
    Expected response (UserSessionCreateResponse):
    {
        "session_id": "...",
        "mgi_token": "..."
    }
    """
    _ = request.get_json(silent=True) or {}   # we ignore the payload for the demo
    session_id = "demo_session_id"
    mgi_token  = "demo_mgi_token"
    sessions[mgi_token] = session_id
    return json_response({"session_id": session_id, "mgi_token": mgi_token})


@app.route("/auth", methods=["GET"])
def auth():
    """
    The game sends an MGI-Bearer-Token header.
    We just need to return a 200 with an empty JSON object (EmptyResponse).
    """
    # Optional: you could verify the token exists in `sessions`
    _ = request.headers.get("MGI-Bearer-Token")
    return json_response({})   # EmptyResponse = {}


# ----------------------------------------------------------------------
# BROWSE / SESSION LISTING
# ----------------------------------------------------------------------
@app.route("/game", methods=["GET"])
def browse():
    """
    Query params: start_idx, max_results, category, val (multiple)
    Expected response (BrowseResponse):
    {
        "games": [ { ...GameSessionInfo... } ]
    }
    """
    # Return an empty list – the game can handle zero results.
    return json_response({"games": []})


@app.route("/game/<game_id>", methods=["GET"])
def game_info(game_id):
    """
    Expected response: same shape as a single element inside BrowseResponse.games
    (i.e. a GameSessionInfo object).  We return a minimal but valid object.
    """
    # Minimal GameSessionInfo – fill in only the fields that are accessed
    # by the client before it decides the session is usable.
    # See GameSessionInfo.cs in the assembly for the full list.
    dummy_info = {
        "id": game_id,
        "srv": {
            "users": 0,
            "cap": 2
        },
        "fields": [],          # the game parses fields via the key list sent in the request
        # The following are optional for the initial browse – we give sane defaults:
        "enableAI": False,
        "enableChat": False,
        "numLaps": 0,
        "league": 0,           # LeagueType.CUP = 0
        "flags": 0,
        "stageCfg": "",
        "state": "lobby",
        "friendlyState": "Lobby",
        "roundId": "",
        "stateTimeout": 0,
        "raceLength": 0,
        "wearFactor": 0,
        "draftInfluence": 0,
        "eventId": "",         # empty string = default EventId
        "eventSetId": "",      # empty string = default EventSetId
        "sessionType": 0,      # NetGameSessionType.PRIVATE = 0
        "gameYear": 0,
        "friendlyTrackName": "",
        "damage": 0,
        "purpose": "",
        "liveDataInterval": 0,
        "isProMode": False,
        "minUsersForScoring": 0,
        "trnclass": 0,
        "purpose": "",
        # The following string fields are often accessed:
        "platformSessionId": "",
        "platformCorrelationId": "",
        "masterUserId": "",
        "masterName": "",
        "masterIsVerified": False,
        "isPrivate": False,
        "forceSimPhysics": False,
        "allowCustomSetups": False,
    }
    # The wrapper that BrowseResponse expects:
    return json_response({"games": [dummy_info]})


@app.route("/game/<game_id>/round/<round_id>", methods=["GET"])
def round_info(game_id, round_id):
    """
    Same shape as /game/<game_id> – the game just wants a GameSessionInfo
    inside the "games" array.
    """
    return game_info(game_id)   # reuse the same dummy


# ----------------------------------------------------------------------
# SESSION MANAGEMENT
# ----------------------------------------------------------------------
@app.route("/game/<game_id>/reservation", methods=["POST"])
def reserve_slots(game_id):
    """
    Expected request: ReservationRequest { "count": <int> }
    Expected response: ReservationResponse (empty – just status 200)
    """
    _ = request.get_json(silent=True) or {}
    return json_response({})


@app.route("/game", methods=["POST"])
def create_game():
    """
    Expected request: GameSessionCreateRequest
    Expected response: GameSessionCreateResponse { "id": "<new‑game‑id>" }
    """
    data = request.get_json(silent=True) or {}
    # In a real server you would validate backend/config etc.
    new_id = f"game_{len(game_sessions) + 1}"
    game_sessions[new_id] = {
        "config": data.get("config", {}),
        "users": [],
    }
    return json_response({"id": new_id})


@app.route("/game/<game_id>/add_user", methods=["POST"])
def add_user(game_id):
    """
    Expected request: JoinRequest { "reservation": "...", "trn_user_subgroup": "..." }
    Expected response: JoinResponse (empty – just status 200)
    """
    _ = request.get_json(silent=True) or {}
    # Create a dummy user if we want to track it
    user_id = f"user_{len(users) + 1}"
    users[user_id] = {"id": user_id}
    if game_id in game_sessions:
        game_sessions[game_id]["users"].append(user_id)
    return json_response({})


@app.route("/game/<game_id>", methods=["POST"])
def set_game_info(game_id):
    """
    Expected request: GameSessionConfigRequest { "config": { ... } }
    Expected response: EmptyResponse (just 200)
    """
    _ = request.get_json(silent=True) or {}
    if game_id in game_sessions:
        # In a real implementation you would merge the config.
        game_sessions[game_id]["config"] = {}
    return json_response({})


@app.route("/game/<game_id>/op/<op>", methods=["POST"])
def game_op(game_id, op):
    """
    Expected request: EmptyRequest
    Expected response: OperationResponse (empty – just 200)
    """
    return json_response({})


@app.route("/game/<game_id>/del_user", methods=["POST"])
def remove_user(game_id):
    """
    Expected request: LeaveRequest { "reason": "..." }
    Expected response: EmptyResponse
    """
    _ = request.get_json(silent=True) or {}
    return json_response({})


@app.route("/game/<game_id>/del_user/<user_id>", methods=["POST"])
def kick_user(game_id, user_id):
    """
    Expected request: EmptyRequest
    Expected response: EmptyResponse
    """
    return json_response({})


# ----------------------------------------------------------------------
# PLAYER INFO
# ----------------------------------------------------------------------
@app.route("/game/<game_id>/round/<round_id>/participants", methods=["GET"])
def participants(game_id, round_id):
    """
    Expected response: UserSessionInfoList { "users": [ { ...UserSessionInfo... } ] }
    """
    return json_response({"users": []})


@app.route("/game/<game_id>/users", methods=["GET"])
def users_in_game(game_id):
    """
    Expected response: UserSessionInfoList
    """
    return json_response({"users": []})


@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    """
    Expected response: UserSessionInfo (many fields – we supply a minimal set)
    """
    dummy_user = {
        "userId": user_id,
        "isLocalUser": False,
        "mpIdx": 0,
        "name": "Player",
        "platformUserId": "",
        "sortVal": 0.0,
        "isVerified": False,
        "basePersonaId": "",
        "appearanceId": "",
        "jingle": "",
        "rollingPoints": 0,
        # The following are optional but appear in the dump; give sensible defaults:
        "badge": None,
    }
    return json_response(dummy_user)


@app.route("/user/config", methods=["POST"])
def set_user_info():
    """
    Expected request: UserSessionConfigRequest { "config": { ... } }
    Expected response: EmptyResponse
    """
    _ = request.get_json(silent=True) or {}
    return json_response({})


# ----------------------------------------------------------------------
# GAMEPLAY EVENTS
# ----------------------------------------------------------------------
@app.route("/game/<game_id>/round/<round_id>/score", methods=["POST"])
def post_score_event(game_id, round_id):
    """
    Expected request: GameSessionScoreEvent (contains LapData or RaceTimeData)
    Expected response: EmptyResponse
    """
    _ = request.get_json(silent=True) or {}
    return json_response({})


# ----------------------------------------------------------------------
# INVITATIONS
# ----------------------------------------------------------------------
@app.route("/invitation/consume", methods=["POST"])
def consume_invitation():
    """
    Expected request: ConsumeInvitationRequest { "invitationId": "..." }
    Expected response: EmptyResponse
    """
    _ = request.get_json(silent=True) or ()
    return json_response({})


@app.route("/invitation/send", methods=["POST"])
def invite_bunch():
    """
    Expected request: MultipleInviteRequest { "platformSessionId": "...", "platformUserIds": [...] }
    Expected response: EmptyResponse
    """
    _ = request.get_json(silent=True) or ()
    return json_response({})


# ----------------------------------------------------------------------
# TELEMETRY
# ----------------------------------------------------------------------
@app.route("/info/connection", methods=["POST"])
def report_connection():
    """
    Expected request: ConnectionInfoMessage (various fields)
    Expected response: EmptyResponse
    """
    _ = request.get_json(silent=True) or ()
    return json_response({})


# ----------------------------------------------------------------------
# NEWS FEED
# ----------------------------------------------------------------------
@app.route("/newsfeed/list", methods=["GET"])
def newsfeed_list():
    """
    Expected response: NewsfeedListResponse { "items": [ { ...NewsfeedItemResponse... } ] }
    """
    return json_response({"items": []})


@app.route("/newsfeed/<int:item_id>", methods=["GET"])
def newsfeed_item(item_id):
    """
    Expected response: NewsfeedItemResponse (many fields – we give a minimal object)
    """
    dummy_item = {
        "id": item_id,
        "title": "Test News",
        "body": "This is a test news item.",
        "timestamp": 0,
        "type": 0,
        "imageUrl": "",
        "linkUrl": "",
    }
    return json_response(dummy_item)


# ----------------------------------------------------------------------
# ANALYTICS
# ----------------------------------------------------------------------
@app.route("/analytics/postrace", methods=["POST"])
def post_race_analytics():
    """
    Expected request: PostRaceAnalyticsData
    Expected response: EmptyResponse
    """
    _ = request.get_json(silent=True) or ()
    return json_response({})


# ----------------------------------------------------------------------
# LEADERBOARDS
# ----------------------------------------------------------------------
@app.route("/leaderboard/<lb_name>/<kind>", methods=["GET"])
def leaderboard_query(lb_name, kind):
    """
    Query string: start_at, count
    Expected response: LeaderboardQueryResponse { "entries": [...], "total": <int> }
    """
    _ = request.args.get("start_at", type=int, default=0)
    _ = request.args.get("count", type=int, default=0)
    return json_response({"entries": [], "total": 0})


@app.route("/leaderboard", methods=["POST"])
def leaderboard_post():
    """
    Expected request: LeaderboardPostRequest { "posts": [LeaderboardPost, ...] }
    Expected response: LeaderboardQueryResponse (same shape as GET)
    """
    _ = request.get_json(silent=True) or ()
    return json_response({"entries": [], "total": 0})


@app.route("/leaderboard/advance_time", methods=["POST"])
def advance_leaderboard_time():
    """
    Expected request: LeaderboardAdvanceTimeRequest { "names": [...] }
    Expected response: LeaderboardQueryResponse
    """
    _ = request.get_json(silent=True) or ()
    return json_response({"entries": [], "total": 0})


# ----------------------------------------------------------------------
# STATS
# ----------------------------------------------------------------------
@app.route("/stats", methods=["GET"])
def get_stats():
    """
    Query string: category
    Expected response: StatsResponse { "values": { ... } }
    """
    _ = request.args.get("category", "")
    return json_response({"values": {}})


# ----------------------------------------------------------------------
# TOURNAMENT
# ----------------------------------------------------------------------
@app.route("/tournament/event_info/<adv>/<subgroup>", methods=["GET"])
def tournament_event_info(adv, subgroup):
    """
    Expected response: TRNEventInfoResponse (many fields – we give a minimal object)
    """
    dummy = {
        "eventId": "",
        "name": "Test Event",
        "description": "",
        "startTime": 0,
        "endTime": 0,
        "isActive": False,
        "reward": "",
        "icon": "",
    }
    return json_response(dummy)


@app.route("/tournament/history/<adv>/<subgroup>", methods=["GET"])
def tournament_history(adv, subgroup):
    """
    Expected response: TRNHistory (list of events – we give empty list)
    """
    return json_response([])   # the wrapper expects a list; the class is just a list wrapper


# ----------------------------------------------------------------------
# CHALLENGES
# ----------------------------------------------------------------------
@app.route("/challenge/list", methods=["GET"])
def challenge_list():
    """
    Query string: limit, published, full
    Expected response: ChallengeListResponse { "challenges": [ ... ] }
    """
    return json_response({"challenges": []})


@app.route("/challenge/leaderboard/<assists_level>", methods=["GET"])
def challenge_leaderboard(assists_level):
    """
    Expected response: ChallengeLeaderboardResponse { "entries": [ ... ] }
    """
    return json_response({"entries": []})


@app.route("/challenge/completed/<challenge_id>", methods=["POST"])
def post_challenge_leaderboard(challenge_id):
    """
    Expected request: ChallengeLeaderboardPostRequest { "score": <float> }
    Expected response: ChallengeLeaderboardResponse
    """
    _ = request.get_json(silent=True) or ()
    return json_response({"entries": []})


# ----------------------------------------------------------------------
# RUN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Turn on debug logging so you can see the raw request/response.
    app.logger.setLevel("DEBUG")
    app.run(host="0.0.0.0", port=8000, debug=True)