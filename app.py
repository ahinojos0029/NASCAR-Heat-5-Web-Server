# app.py – NASCAR Heat 5 emulator (Flask) that works with UnityWebRequest
# ----------------------------------------------------------------------
# * Adds the ACTUAL-STATUS-CODE header that Unity expects
# * Always returns JSON with correct Content-Type
# * Never falls back to Flask's HTML error pages
# * Reads $PORT from the environment (Railway, localhost, etc.)
# ----------------------------------------------------------------------

import json
import os
import uuid
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

# ----------------------------------------------------------------------
# In‑memory stores (same as before)
# ----------------------------------------------------------------------
sessions = {}          # token -> {"session_id": str, "user_id": str}
users   = {}           # user_id -> dict with user fields
games   = {}           # game_id -> {"config":{}, "users":set(),
                       #            "reservations":int, "scores":{}}
leaderboards = {}
newsfeed_items = [{
    "id": 1,
    "title": "Welcome to NASCAR Heat 5",
    "body": "Enjoy the races!",
    "timestamp": 0,
    "type": 0,
    "imageUrl": "",
    "linkUrl": ""
}]
tournament_events = []
tournament_history = []
challenges = []
stats_values = {}

# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------
def make_token():    return str(uuid.uuid4())
def make_session_id(): return str(uuid.uuid4())
def make_user_id():    return str(uuid.uuid4())
def make_game_id():    return f"game_{len(games) + 1}"

def json_response(data, status=200):
    """
    Return a Flask Response that:
      * has application/json Content‑Type
      * carries the ACTUAL-STATUS-CODE header Unity reads
      * contains the JSON‑serialized *data* (even for errors)
    """
    resp = jsonify(data)
    resp.status_code = status
    resp.headers["Content-Type"] = "application/json"
    # UnityWebRequest.ActiveStatusCode() reads this header
    resp.headers["ACTUAL-STATUS-CODE"] = str(status)
    return resp

def require_auth():
    """Validate MGI‑Bearer‑Token; abort 401 if missing/invalid."""
    token = request.headers.get("MGI-Bearer-Token")
    if token not in sessions:
        abort(401, description="Invalid or missing token")
    return sessions[token]   # {"session_id":…, "user_id":…}

# ----------------------------------------------------------------------
# Request / Response logging (INFO level – visible in Railway logs)
# ----------------------------------------------------------------------
@app.before_request
def _log_request():
    body = request.get_data()
    body_preview = (
        body[:200].decode('utf-8', errors='replace')
        if body else ''
    )
    app.logger.info(
        ">>> %s %s\nHeaders: %s\nBody (%d bytes): %s",
        request.method, request.path,
        dict(request.headers),
        len(body), body_preview
    )

@app.after_request
def _log_response(response):
    data = response.get_data()
    data_preview = (
        data[:200].decode('utf-8', errors='replace')
        if data else ''
    )
    app.logger.info(
        "<<< %s %s\nHeaders: %s\nBody (%d bytes): %s",
        response.status, response.status_code,
        dict(response.headers),
        len(data), data_preview
    )
    return response

# ----------------------------------------------------------------------
# Generic JSON error handlers – never return HTML
# ----------------------------------------------------------------------
@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(500)
def json_error(e):
    # Always return JSON, never Flask's default HTML page
    return json_response({"error": str(e)}), getattr(e, "code", 500)

# ----------------------------------------------------------------------
# AUTHENTICATION
# ----------------------------------------------------------------------
@app.route("/user", methods=["POST"])
def create_user():
    """
    Request: UserSessionCreateResponse
    Response: { "session_id": "...", "mgi_token": "..." }
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)

    _ = payload  # we don’t need the fields for the emulator
    user_id = make_user_id()
    token   = make_token()
    session_id = make_session_id()
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
        "badge": None,
    }
    sessions[token] = {"session_id": session_id, "user_id": user_id}
    return json_response({"session_id": session_id, "mgi_token": token})

@app.route("/auth", methods=["GET"])
def auth():
    """
    The game only needs a successful 200 response.
    We ignore the token here – always return {}.
    """
    return json_response({})   # EmptyResponse

# ----------------------------------------------------------------------
# BROWSE / SESSION LISTING
# ----------------------------------------------------------------------
@app.route("/game", methods=["GET"])
def browse():
    start = int(request.args.get("start_idx", 0))
    max_results = int(request.args.get("max_results", 20))
    game_list = []
    for gid, g in list(games.items())[start:start+max_results]:
        game_list.append(build_game_session_info(gid, g))
    return json_response({"games": game_list})

@app.route("/game/<game_id>", methods=["GET"])
def game_info(game_id):
    if game_id not in games:
        gid = game_id
        g   = {"config": {}, "users": set()}
    else:
        gid, g = game_id, games[game_id]
    return json_response({"games": [build_game_session_info(gid, g)]})

@app.route("/game/<game_id>/round/<round_id>", methods=["GET"])
def round_info(game_id, round_id):
    # Same as game_info but we overwrite roundId later.
    resp = game_info(game_id)          # reuse the same logic
    data = resp.get_json()
    if data and data.get("games"):
        data["games"][0]["roundId"] = str(round_id)
        return json_response(data)
    return resp   # fallback (should never happen)

def build_game_session_info(game_id, game_data):
    config = game_data.get("config", {})
    return {
        "id": game_id,
        "srv": {
            "users": len(game_data.get("users", set())),
            "cap": config.get("capacity", 2),
        },
        "fields": [],
        "enableAI": config.get("enableAI", False),
        "enableChat": config.get("enableChat", False),
        "numLaps":    config.get("numLaps", 0),
        "league":     config.get("league", 0),               # 0 = CUP
        "flags":      config.get("flags", 0),
        "stageCfg":   config.get("stageCfg", ""),
        "state":      "lobby",
        "friendlyState":"Lobby",
        "roundId":    "",
        "stateTimeout":0,
        "raceLength":0,
        "wearFactor":0,
        "draftInfluence":0,
        "eventId":"",
        "eventSetId":"",
        "sessionType":0,
        "gameYear":0,
        "friendlyTrackName": config.get("friendlyTrackName", ""),
        "damage": config.get("damage", 0),
        "purpose":"",
        "liveDataInterval":0,
        "isProMode":False,
        "minUsersForScoring":0,
        "trnclass":0,
        "platformSessionId":"",
        "platformCorrelationId":"",
        "masterUserId":"",
        "masterName":"",
        "masterIsVerified":False,
        "isPrivate": config.get("isPrivate", False),
        "forceSimPhysics": config.get("forceSimPhysics", False),
        "allowCustomSetups": config.get("allowCustomSetups", False),
    }

# ----------------------------------------------------------------------
# SESSION MANAGEMENT
# ----------------------------------------------------------------------
@app.route("/game/<game_id>/reservation", methods=["POST"])
def reserve_slots(game_id):
    if game_id not in games:
        games[game_id] = {"config":{}, "users":set(), "reservations":0, "scores":{}}
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    games[game_id]["reservations"] = payload.get("count", 0)
    return json_response({})

@app.route("/game", methods=["POST"])
def create_game():
    """
    Expected request: GameSessionCreateRequest
    {
        "backend":   {...},
        "config":    {...},
        "category":  "...",
        "tid":       {...}
    }
    Expected response: GameSessionCreateResponse { "id": "<new‑game‑id>" }
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)

    # We don’t need to validate the inner objects for the emulator,
    # but we keep them so the stored game reflects what the client sent.
    gid = make_game_id()
    games[gid] = {
        "config": payload.get("config", {}),
        "users": set(),
        "reservations": 0,
        "scores": {}
    }

    # The real service only returns the id; we mirror that.
    return json_response({"id": gid})

@app.route("/game/<game_id>/add_user", methods=["POST"])
def add_user(game_id):
    """
    Request: JoinRequest { "reservation": "...", "trn_user_subgroup": "..." }
    Response: JoinResponse (empty JSON)
    """
    sess = require_auth()
    user_id = sess["user_id"]
    if game_id not in games:
        # If the game does not exist yet, create a stub so the call succeeds.
        games[game_id] = {"config":{}, "users":set(), "reservations":0, "scores":{}}
    games[game_id]["users"].add(user_id)
    return json_response({})

@app.route("/game/<game_id>", methods=["POST"])
def set_game_info(game_id):
    """
    Request: GameSessionConfigRequest { "config": {...} }
    Response: EmptyResponse
    """
    if game_id not in games:
        games[game_id] = {"config":{}, "users":set(), "reservations":0, "scores":{}}
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    games[game_id]["config"].update(payload.get("config", {}))
    return json_response({})

@app.route("/game/<game_id>/op/<op>", methods=["POST"])
def game_op(game_id, op):
    # No state change needed for the emulator.
    return json_response({})

@app.route("/game/<game_id>/del_user", methods=["POST"])
def remove_user(game_id):
    sess = require_auth()
    user_id = sess["user_id"]
    if game_id in games:
        games[game_id]["users"].discard(user_id)
    return json_response({})

@app.route("/game/<game_id>/del_user/<user_id>", methods=["POST"])
def kick_user(game_id, user_id):
    if game_id in games:
        games[game_id]["users"].discard(user_id)
    return json_response({})

# ----------------------------------------------------------------------
# PLAYER INFO
# ----------------------------------------------------------------------
@app.route("/game/<game_id>/round/<round_id>/participants", methods=["GET"])
def participants(game_id, round_id):
    if game_id not in games:
        return json_response({"users": []})
    sess = require_auth()
    local_user_id = sess["user_id"]
    user_list = []
    for idx, uid in enumerate(games[game_id]["users"]):
        u = users.get(uid, {})
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
    # Same as participants – round_id is irrelevant here.
    return participants(game_id, "0")

@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    if user_id not in users:
        # Return a minimal placeholder – prevents 404.
        u = {
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
            "badge": None,
        }
    else:
        u = users[user_id]
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
        "badge": u.get("badge", None),
    }
    return json_response(resp)

@app.route("/user/config", methods=["POST"])
def set_user_info():
    sess = require_auth()
    user_id = sess["user_id"]
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    cfg = payload.get("config", {})
    if user_id in users:
        users[user_id].update(cfg)
    else:
        # create a stub if somehow missing
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
            "badge": None,
        }
        users[user_id].update(cfg)
    return json_response({})

# ----------------------------------------------------------------------
# GAMEPLAY EVENTS (lap / race scores)
# ----------------------------------------------------------------------
@app.route("/game/<game_id>/round/<round_id>/score", methods=["POST"])
def post_score_event(game_id, round_id):
    if game_id not in games:
        games[game_id] = {"config":{}, "users":set(), "reservations":0, "scores":{}}
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    event = {
        "lapData": payload.get("data"),          # may be None
        "raceTimeData": payload.get("racetime_data")
    }
    games[game_id]["scores"].setdefault(round_id, []).append(event)
    return json_response({})

# ----------------------------------------------------------------------
# INVITATIONS
# ----------------------------------------------------------------------
@app.route("/invitation/consume", methods=["POST"])
def consume_invitation():
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    return json_response({})

@app.route("/invitation/send", methods=["POST"])
def invite_bunch():
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    return json_response({})

# ----------------------------------------------------------------------
# TELEMETRY
# ----------------------------------------------------------------------
@app.route("/info/connection", methods=["POST"])
def report_connection():
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    return json_response({})

# ----------------------------------------------------------------------
# NEWS FEED
# ----------------------------------------------------------------------
@app.route("/newsfeed/list", methods=["GET"])
def newsfeed_list():
    return json_response({"items": newsfeed_items})

@app.route("/newsfeed/<int:item_id>", methods=["GET"])
def newsfeed_item(item_id):
    for item in newsfeed_items:
        if item["id"] == item_id:
            return json_response(item)
    # Not found – still return JSON (400/404 would be HTML otherwise)
    return json_response({"error": "not found"}), 404

# ----------------------------------------------------------------------
# ANALYTICS
# ----------------------------------------------------------------------
@app.route("/analytics/postrace", methods=["POST"])
def post_race_analytics():
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    return json_response({})

# ----------------------------------------------------------------------
# LEADERBOARDS
# ----------------------------------------------------------------------
@app.route("/leaderboard/<lb_name>/<kind>", methods=["GET"])
def leaderboard_query(lb_name, kind):
    start = int(request.args.get("start_at", 0))
    cnt   = int(request.args.get("count", 0))
    entries = leaderboards.get(lb_name, [])
    sliced  = entries[start:start+cnt]
    return json_response({"entries": sliced, "total": len(entries)})

@app.route("/leaderboard", methods=["POST"])
def leaderboard_post():
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    posts = payload.get("posts", [])
    lb_name = "global"               # simple fallback
    leaderboards.setdefault(lb_name, []).extend(posts)
    return json_response({"entries": leaderboards[lb_name][-len(posts):],
                          "total": len(leaderboards[lb_name])})

@app.route("/leaderboard/advance_time", methods=["POST"])
def advance_leaderboard_time():
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    return json_response({"entries": [], "total": 0})

# ----------------------------------------------------------------------
# STATS
# ----------------------------------------------------------------------
@app.route("/stats", methods=["GET"])
def get_stats():
    category = request.args.get("category", "")
    return json_response({"values": stats_values.get(category, {})})

# ----------------------------------------------------------------------
# TOURNAMENT
# ----------------------------------------------------------------------
@app.route("/tournament/event_info/<adv>/<subgroup>", methods=["GET"])
def tournament_event_info(adv, subgroup):
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
    # The wrapper expects a list; we return an empty list.
    return json_response([])

# ----------------------------------------------------------------------
# CHALLENGES
# ----------------------------------------------------------------------
@app.route("/challenge/list", methods=["GET"])
def challenge_list():
    return json_response({"challenges": challenges})

@app.route("/challenge/leaderboard/<assists_level>", methods=["GET"])
def challenge_leaderboard(assists_level):
    return json_response({"entries": []})

@app.route("/challenge/completed/<challenge_id>", methods=["POST"])
def post_challenge_leaderboard(challenge_id):
    payload = request.get_json(silent=True)
    if payload is None:
        return json_response({"error": "invalid JSON"}, 400)
    return json_response({"entries": []})

# ----------------------------------------------------------------------
# RUN – read PORT from the environment (Railway sets $PORT)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # When running locally you can still use `python app.py`
    # Railway will invoke the Procfile (see below) which uses gunicorn.
    port = int(os.environ.get("PORT", 8000))
    # Use INFO level so request/response logs appear in Railway logs
    app.logger.setLevel("INFO")
    app.run(host="0.0.0.0", port=port, debug=False)
