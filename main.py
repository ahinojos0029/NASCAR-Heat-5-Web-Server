"""
NASCAR Heat 5 - Multiplayer Server Emulator
Reverse engineered from MGI/704Games WebapiBridge
Base URLs: https://n2020.mgrsys.com/ / https://n2022.mgrsys.com/

Patch GetBaseURL() in your DLL to point here:
  return "http://127.0.0.1:8000/";

Run: pip install flask && python nh5_server.py
"""

import uuid
import secrets
import os
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

# ── In-memory state ──────────────────────────────────────────────────────────
users    = {}   # mgi_token -> { session_id, steam_id, name, config, game_id }
sessions = {}   # game_id   -> { category, capacity, config, users[], state, round_id }

# ── Helpers ──────────────────────────────────────────────────────────────────

def make_token():
    return secrets.token_hex(32)

def make_id():
    return str(uuid.uuid4())

def get_token(req):
    """Extract mgi-bearer-token from request headers."""
    return req.headers.get("Mgi-Bearer-Token") or req.headers.get("mgi-bearer-token")

def get_user(req):
    """
    Resolve caller from mgi-bearer-token header.
    If token is missing/unknown, create a guest user automatically
    so the game never gets blocked by auth.
    """
    token = get_token(req)
    if not token:
        abort(403)
    if token not in users:
        # Auto-register unknown tokens (handles "invalid" default token)
        session_id = make_id()
        users[token] = {
            "session_id": session_id,
            "steam_id":   "unknown",
            "name":       "Player",
            "config":     {},
            "game_id":    None,
        }
        print(f"   [AUTO-REGISTER] token={token[:8]}... session={session_id[:8]}...")
    return token, users[token]

def make_cipher_data():
    data = {
        "iv":           list(os.urandom(16)),
        "aes_key":      list(os.urandom(32)),
        "hmac_key":     list(os.urandom(32)),
        "conn_suffix":  list(os.urandom(32)),
        "conn_message": list(os.urandom(32)),
        "resp_message": list(os.urandom(32)),
    }
    print(f"   [CIPHER] iv={len(data['iv'])} aes={len(data['aes_key'])} hmac={len(data['hmac_key'])} suffix={len(data['conn_suffix'])} conn={len(data['conn_message'])} resp={len(data['resp_message'])}")
    return data

def make_isn():
    return {
        "srv_seq": secrets.randbits(32),
        "cli_seq": secrets.randbits(32),
    }

def build_game_session_info(game_id):
    s = sessions[game_id]
    cfg = s["config"]
    # Get the requested keys from the current request context
    keys = request.args.getlist("val")
    if keys:
        fields = [cfg.get(k, "") for k in keys]
    else:
        fields = list(cfg.values())
    return {
        "id": game_id,
        "srv": {
            "users": len(s["users"]),
            "cap":   s["capacity"],
        },
        "fields": fields,
    }

# ── Logging middleware ────────────────────────────────────────────────────────

@app.before_request
def log_req():
    print(f"\n>> {request.method} {request.path}")
    token = get_token(request)
    if token:
        print(f"   Token: {token[:8]}...")
    body = request.get_data(as_text=True)
    if body:
        print(f"   Body: {body[:300]}")

@app.after_request
def log_resp(response):
    response.headers["ACTUAL-STATUS-CODE"] = str(response.status_code)
    print(f"   <- {response.status_code}")
    return response

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/user")
def login():
    """
    WebapiBridge.Login()
    Client POSTs Steam ticket / platform user info.
    Returns mgi_token + session_id without validating Steam.
    """
    body       = request.get_json(silent=True) or {}
    steam_id   = str(body.get("platform_user_id", make_id()))
    name       = body.get("name", "Player")
    token      = make_token()
    session_id = make_id()
    users[token] = {
        "session_id": session_id,
        "steam_id":   steam_id,
        "name":       name,
        "config":     {},
        "game_id":    None,
    }
    print(f"   [LOGIN] {name} steam={steam_id} token={token[:8]}...")
    return jsonify({
        "mgi_token":  token,
        "session_id": session_id,
    })

@app.get("/auth")
def test_auth():
    """
    WebapiBridge.TestAuth()
    Always return 200 — the default token is literally "invalid" and
    re-auth only fires if m_plat_auth != null which may not be guaranteed.
    We handle identity via auto-register in get_user() instead.
    """
    get_user(request)
    return jsonify({})

# ── Game session (lobby) ──────────────────────────────────────────────────────

@app.post("/game")
def create_game():
    """WebapiBridge.CreateGameSession()"""
    token, user = get_user(request)
    body     = request.get_json(silent=True) or {}
    config   = dict(body.get("config", {}))
    capacity = body.get("backend", {}).get("capacity", 8)
    category = body.get("category", "N2020")
    game_id  = make_id()

    # Inject server-managed state fields
    config["s.state"]                   = "lobby"
    config["s.friendly_state"]          = "In Lobby"
    config["s.master_user_id"]          = user["session_id"]
    config["s.master_name"]             = user["name"]
    config["s.master_is_verified"]      = "false"
    config["s.platform_session_id"]     = make_id()
    config["s.platform_correlation_id"] = make_id()
    config["s.round_id"]                = ""
    config["s.state_timeout"]           = "-1"
    config["s.purpose"]                 = "RACE"
    config["s.livedata_interval"]       = "0"
    config["s.is_pro_mode"]             = "false"
    config["s.min_users_for_scoring"]   = "1"
    config["s.trnclass"]                = ""
    config["s.driving_backwards_rule"]  = ""

    sessions[game_id] = {
        "category": category,
        "capacity": capacity,
        "config":   config,
        "users":    [],
        "state":    "lobby",
        "round_id": None,
    }
    print(f"   [CREATE] game={game_id} cat={category} cap={capacity}")
    return jsonify({"id": game_id})

@app.get("/game")
def browse():
    """WebapiBridge.Browse()"""
    get_user(request)
    category    = request.args.get("category", "N2020")
    start_idx   = int(request.args.get("start_idx",   0))
    max_results = int(request.args.get("max_results", 20))

    matching = [
        build_game_session_info(gid)
        for gid, s in sessions.items()
        if s["category"] == category or category == "ALL_PLATFORMS"
    ]
    page = matching[start_idx: start_idx + max_results]
    print(f"   [BROWSE] cat={category} results={len(page)}")
    return jsonify({"games": page})

@app.get("/game/<game_id>")
def get_game_info(game_id):
    """WebapiBridge.GetGameInfo()"""
    get_user(request)
    if game_id not in sessions:
        return jsonify({"games": []})
    return jsonify({"games": [build_game_session_info(game_id)]})

@app.post("/game/<game_id>")
def set_game_info(game_id):
    """WebapiBridge.SetGameInfo()"""
    token, user = get_user(request)
    if game_id not in sessions:
        abort(404)
    body   = request.get_json(silent=True) or {}
    config = body.get("config", {})
    sessions[game_id]["config"].update(config)
    print(f"   [SET_INFO] game={game_id} keys={list(config.keys())}")
    return jsonify({})

@app.post("/game/<game_id>/add_user")
def join_game(game_id):
    """
    WebapiBridge.JoinGameSession()
    Returns JoinResponse — must include game_id, mpidx, ip, cipher, isn
    per BackendAddUserResponse / handle_successful_join_f in NetBridge.
    """
    token, user = get_user(request)
    if game_id not in sessions:
        abort(404)
    s = sessions[game_id]
    if len(s["users"]) >= s["capacity"]:
        return jsonify({"error": {"sc": 429, "description": "Session full"}}), 429

    # Assign multiplayer slot index
    used  = {u["mpidx"] for u in s["users"]}
    mpidx = next(i for i in range(s["capacity"]) if i not in used)

    s["users"].append({
        "session_id": user["session_id"],
        "token":      token,
        "mpidx":      mpidx,
        "config":     dict(user["config"]),
        "state":      "lobby",
    })
    users[token]["game_id"] = game_id

    print(f"   [JOIN] user={user['session_id'][:8]}... game={game_id} mpidx={mpidx}")
    return jsonify({
        "game_id": game_id,
        "backend": {
            "mpidx":  mpidx,
            "ip":     "0.0.0.0",  # Update for LAN/public hosting
            "cipher": make_cipher_data(),
            "isn":    make_isn(),
        }
    })

@app.post("/game/<game_id>/del_user")
def leave_game(game_id):
    """WebapiBridge.LeaveGameSession()"""
    token, user = get_user(request)
    if game_id in sessions:
        s = sessions[game_id]
        s["users"] = [u for u in s["users"] if u["token"] != token]
        if not s["users"]:
            del sessions[game_id]
            print(f"   [LEAVE] game={game_id} deleted (empty)")
        else:
            print(f"   [LEAVE] user={user['session_id'][:8]}... left game={game_id}")
    users[token]["game_id"] = None
    return jsonify({})

@app.post("/game/<game_id>/del_user/<user_session_id>")
def kick_user(game_id, user_session_id):
    """WebapiBridge.KickUser()"""
    get_user(request)
    if game_id in sessions:
        sessions[game_id]["users"] = [
            u for u in sessions[game_id]["users"]
            if u["session_id"] != user_session_id
        ]
    print(f"   [KICK] {user_session_id[:8]}... from game={game_id}")
    return jsonify({})

@app.post("/game/<game_id>/op/<operation>")
def do_game_op(game_id, operation):
    """WebapiBridge.DoGameOperation() — lobby state machine."""
    get_user(request)
    if game_id not in sessions:
        abort(404)
    s = sessions[game_id]
    print(f"   [OP] game={game_id} op={operation}")

    if operation == "start":
        round_id = make_id()
        s["round_id"] = round_id
        s["state"]    = "load_and_sync"
        s["config"].update({
            "s.state":          "load_and_sync",
            "s.friendly_state": "Loading",
            "s.round_id":       round_id,
            "s.state_timeout":  "60",
        })
    elif operation == "ready":
        s["state"] = "racing"
        s["config"].update({
            "s.state":          "racing",
            "s.friendly_state": "Racing",
            "s.state_timeout":  "-1",
        })
    elif operation == "finish":
        s["state"] = "postrace"
        s["config"].update({
            "s.state":          "postrace",
            "s.friendly_state": "Post Race",
            "s.state_timeout":  "-1",
        })
    elif operation == "reset":
        s["state"]    = "lobby"
        s["round_id"] = None
        s["config"].update({
            "s.state":          "lobby",
            "s.friendly_state": "In Lobby",
            "s.round_id":       "",
            "s.state_timeout":  "-1",
        })

    return jsonify({"op": operation, "result": "ok"})

@app.post("/game/<game_id>/reservation")
def reserve_slots(game_id):
    """WebapiBridge.ReserveSlots()"""
    get_user(request)
    return jsonify({"reservation_id": make_id()})

# ── Round info ────────────────────────────────────────────────────────────────

@app.get("/game/<game_id>/round/<round_id>")
def get_round_info(game_id, round_id):
    """WebapiBridge.GetRoundInfo()"""
    get_user(request)
    if game_id not in sessions:
        return jsonify({"games": []})
    return jsonify({"games": [build_game_session_info(game_id)]})

@app.get("/game/<game_id>/round/<round_id>/participants")
def get_round_participants(game_id, round_id):
    """WebapiBridge.GetParticipantInfoForRound()"""
    get_user(request)
    if game_id not in sessions:
        return jsonify({"users": []})
    s = sessions[game_id]
    return jsonify({
        "users": [
            {"user": {"user": u["session_id"], "idx": u["mpidx"]}, "fields": []}
            for u in s["users"]
        ]
    })

@app.post("/game/<game_id>/round/<round_id>/score")
def post_score(game_id, round_id):
    """WebapiBridge.PostScoreEvent()"""
    get_user(request)
    print(f"   [SCORE] game={game_id} round={round_id}")
    return jsonify({})

# ── User info ─────────────────────────────────────────────────────────────────

@app.get("/game/<game_id>/users")
def get_users_for_game(game_id):
    """WebapiBridge.GetUserInfoForGameSession()"""
    get_user(request)
    keys = request.args.getlist("val")
    if game_id not in sessions:
        return jsonify({"users": []})
    s   = sessions[game_id]
    out = []
    for u in s["users"]:
        user_data = users.get(u["token"], {})
        cfg    = {**user_data.get("config", {}), **u.get("config", {})}
        fields = [cfg.get(k, "") for k in keys]
        out.append({
            "user":   {"user": u["session_id"], "idx": u["mpidx"]},
            "fields": fields,
        })
    return jsonify({"users": out})

@app.post("/user/config")
def set_user_config():
    """WebapiBridge.SetUserInfo()"""
    token, user = get_user(request)
    body   = request.get_json(silent=True) or {}
    config = body.get("config", {})
    users[token]["config"].update(config)
    game_id = users[token].get("game_id")
    if game_id and game_id in sessions:
        for u in sessions[game_id]["users"]:
            if u["token"] == token:
                u["config"].update(config)
                break
    return jsonify({})

@app.get("/user/<user_session_id>")
def get_user_info(user_session_id):
    """WebapiBridge.GetUserInfo()"""
    get_user(request)
    target = next((u for u in users.values() if u["session_id"] == user_session_id), None)
    if not target:
        abort(404)
    return jsonify({"user": {"user": user_session_id, "idx": 0}, "fields": []})

# ── Connection reporting ───────────────────────────────────────────────────────

@app.post("/info/connection")
def report_connection_info():
    """WebapiBridge.ReportConnectionInfo()"""
    get_user(request)
    print(f"   [CONN_INFO] {request.get_json(silent=True)}")
    return jsonify({})

# ── Invitations ────────────────────────────────────────────────────────────────

@app.post("/invitation/consume")
def consume_invitation():
    get_user(request)
    return jsonify({})

@app.post("/invitation/send")
def send_invitation():
    get_user(request)
    return jsonify({})

# ── Leaderboards ───────────────────────────────────────────────────────────────

@app.get("/leaderboard/<lb_name>/<kind>")
def leaderboard_query(lb_name, kind):
    get_user(request)
    return jsonify({"entries": []})

@app.post("/leaderboard")
def leaderboard_post():
    get_user(request)
    return jsonify({"entries": []})

@app.post("/leaderboard/advance_time")
def leaderboard_advance_time():
    get_user(request)
    return jsonify({})

# ── Stats ──────────────────────────────────────────────────────────────────────

@app.get("/stats")
def get_stats():
    get_user(request)
    return jsonify({
        "online_players":  len(users),
        "active_sessions": len(sessions),
    })

# ── Newsfeed (no auth) ─────────────────────────────────────────────────────────

@app.get("/newsfeed/list")
def newsfeed_list():
    return jsonify({"items": []})

@app.get("/newsfeed/<int:item_id>")
def newsfeed_item(item_id):
    return jsonify({"item": None})

# ── Analytics (no auth) ────────────────────────────────────────────────────────

@app.post("/analytics/postrace")
def post_race_analytics():
    return jsonify({})

# ── Tournament (stub) ──────────────────────────────────────────────────────────

@app.get("/tournament/event_info/<adv>/<subgroup>")
def tournament_event_info(adv, subgroup):
    get_user(request)
    return jsonify({})

@app.get("/tournament/history/<adv>/<subgroup>")
def tournament_history(adv, subgroup):
    get_user(request)
    return jsonify({})

# ── Challenge (stub) ───────────────────────────────────────────────────────────

@app.get("/challenge/list")
def challenge_list():
    get_user(request)
    return jsonify({"challenges": []})

@app.get("/challenge/leaderboard/<assists_level>")
def challenge_leaderboard(assists_level):
    get_user(request)
    return jsonify({"entries": []})

@app.post("/challenge/completed/<int:challenge_id>")
def post_challenge(challenge_id):
    get_user(request)
    return jsonify({})

# ── Debug ──────────────────────────────────────────────────────────────────────

@app.get("/debug/state")
def debug_state():
    return jsonify({
        "connected_users": len(users),
        "sessions": {
            gid: {
                "category": s["category"],
                "state":    s["state"],
                "players":  len(s["users"]),
                "capacity": s["capacity"],
            }
            for gid, s in sessions.items()
        }
    })

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("NASCAR Heat 5 - Server Emulator")
    print("Endpoints: http://127.0.0.1:8000/")
    print("Debug:     http://127.0.0.1:8000/debug/state")
    print()
    app.run(host="0.0.0.0", port=8000, debug=True)