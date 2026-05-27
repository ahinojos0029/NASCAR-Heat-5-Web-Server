from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
import uuid
import time
import socket

app = FastAPI()

# ---------------- MIDDLEWARE ----------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"\n----- {request.method} {request.url.path} -----")
    body = await request.body()
    if body:
        print("Body:", body.decode())
    response = await call_next(request)
    print("Response Status:", response.status_code)
    return response

# ---------------- DATA ----------------
users = {}    # session_id -> user data
tokens = {}   # mgi_token -> session_id
games = {}    # game_id -> game data

leaderboards = {}

# ---------------- HELPERS ----------------
def get_local_ip():
    """Get the LAN IP so game clients can actually connect."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()
print(f"[SERVER] Local IP for backend responses: {LOCAL_IP}")

def response(data, code=200):
    import json
    print(f"Returning JSON (status {code}):")
    print(json.dumps(data, indent=2))
    # Use status_code on JSONResponse so the game actually sees 4xx errors
    r = JSONResponse(content=data, status_code=code)
    return r

def generate_backend(session_index=0):
    """Generate a backend object compatible with JoinResponse.IsValid()"""
    return {
        "mpidx": session_index,
        "cipher": {"key": "localdevkey", "iv": "localiv"},
        "isn": {"send": 1, "recv": 1},
        "ip": LOCAL_IP   # must be reachable by the client, not 0.0.0.0
    }

def build_game_response(gid, g, viewer_session=None):
    """
    Build a full game response.
    viewer_session: if provided, use that player's mpidx for the backend object
    (matters for add_user responses; for list_games it's fine as 0)
    """
    players = g.get("players", [])
    if viewer_session and viewer_session in players:
        session_index = players.index(viewer_session)
    else:
        session_index = 0

    return {
        "id": gid,
        "s": {
            "master_user_id": g["master_user_id"],
            "master_name": g["master_name"],
            "master_is_verified": g["master_is_verified"],
            "state": g["state"],
            "friendly_state": g["friendly_state"],
            "round_id": g["round_id"],
            "state_timeout": g["state_timeout"],
            "platform_session_id": g["platform_session_id"],
            "platform_correlation_id": g["platform_correlation_id"],
            "driving_backwards_rule": g["driving_backwards_rule"],
            "trnclass": g["trnclass"],
            "purpose": g["purpose"],
            "livedata_interval": g["livedata_interval"],
            "is_pro_mode": g["is_pro_mode"],
            "min_users_for_scoring": g["min_users_for_scoring"],
        },
        "c": {
            "is_private": g["is_private"],
            "force_sim_physics": g["force_sim_physics"],
            "allow_custom_setups": g["allow_custom_setups"],
        },
        "race_length": g["race_length"],
        "num_laps": g["num_laps"],
        "wear_factor": g["wear_factor"],
        "flags": g["flags"],
        "event_id": g["event_id"],
        "event_set_id": g["event_set_id"],
        "session_type": g["session_type"],
        "damage": g["damage"],
        "league": g["league"],
        "stage_cfg": g["stage_cfg"],
        "enable_chat": g["enable_chat"],
        "enable_ai": g["enable_ai"],
        "friendly_track_name": g["friendly_track_name"],
        "game_year": g["game_year"],
        "draft_influence": g["draft_influence"],
        "backend": generate_backend(session_index),
    }

# ---------------- USER ----------------
@app.post("/user")
async def create_user(req: dict):
    session_id = str(uuid.uuid4())
    token = str(uuid.uuid4())
    # Store whatever name/platform the client sends
    users[session_id] = {
        "created": time.time(),
        "platform": req.get("platform", "unknown"),
        "name": req.get("name") or req.get("username") or "player",
        "version": req.get("version", ""),
        "client_version": req.get("client_version", ""),
    }
    tokens[token] = session_id
    return response({"session_id": session_id, "mgi_token": token})

@app.get("/auth")
async def auth(mgi_bearer_token: str = Header(None)):
    if mgi_bearer_token not in tokens:
        return response({"error": "invalid token"}, 403)
    return response({"status": "ok"})

@app.get("/user/{user_id}")
async def get_user(user_id: str):
    if user_id not in users:
        return response({"error": "user not found"}, 404)
    u = users[user_id]
    return response({"id": user_id, "name": u.get("name", "player")})

@app.post("/user/config")
async def user_config(req: dict):
    return response({"status": "saved"})

# ---------------- GAME ----------------
@app.post("/game")
async def create_game(req: dict = {}, mgi_bearer_token: str = Header(None)):
    if mgi_bearer_token not in tokens:
        return response({"error": "invalid token"}, 403)

    session = tokens[mgi_bearer_token]
    user = users.get(session, {})
    cfg = req.get("config", {})
    backend_cfg = req.get("backend", {})

    game_id = str(uuid.uuid4())

    # Pull values from the client request; fall back to sane defaults only
    # when the field is genuinely absent
    def bool_cfg(key, default=False):
        v = cfg.get(key)
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        return str(v).lower() == "true"

    g = {
        "players": [session],
        "max_players": backend_cfg.get("capacity", 20),
        "state": 0,
        "friendly_state": "LOBBY",
        "round_id": str(uuid.uuid4()),
        "state_timeout": 0,
        # Track/event info comes from the client; we store what they send
        "race_length": cfg.get("race_length", 10),
        "num_laps": cfg.get("num_laps") or cfg.get("race_length") or 10,
        "wear_factor": float(cfg.get("wear_factor", 1.0)),
        "flags": cfg.get("flags", []),
        "event_id": cfg.get("event_id", ""),
        "event_set_id": cfg.get("event_set_id", ""),
        "session_type": cfg.get("session_type", "NORMAL"),
        "platform_session_id": str(uuid.uuid4()),
        "platform_correlation_id": str(uuid.uuid4()),
        "driving_backwards_rule": bool_cfg("driving_backwards_rule", False),
        "is_private": bool_cfg("c.is_private", False),
        "force_sim_physics": bool_cfg("c.force_sim_physics", False),
        "allow_custom_setups": bool_cfg("c.allow_custom_setups", False),
        "damage": cfg.get("damage", "FULL"),
        "league": cfg.get("league", "CUP"),
        "stage_cfg": cfg.get("stage_cfg", []),
        "enable_chat": bool_cfg("enable_chat", False),
        "enable_ai": bool_cfg("enable_ai", False),
        "trnclass": cfg.get("trnclass") or req.get("category", "N2020"),
        "friendly_track_name": cfg.get("friendly_track_name", ""),
        "game_year": cfg.get("game_year", "PRESENT"),
        "purpose": cfg.get("purpose", "RACE"),
        "livedata_interval": int(cfg.get("livedata_interval", 1000)),
        "is_pro_mode": bool_cfg("is_pro_mode", False),
        "draft_influence": float(cfg.get("draft_influence", 1.0)),
        "min_users_for_scoring": int(cfg.get("min_users_for_scoring", 1)),
        # Host identity comes from their user record
        "master_user_id": session,
        "master_name": user.get("name", "player"),
        "master_is_verified": True,
    }
    games[game_id] = g
    return response(build_game_response(game_id, g, viewer_session=session))

@app.get("/game")
async def list_games(
    start_idx: int = 0,
    max_results: int = 200,
    category: str = "",
    mgi_bearer_token: str = Header(None),
):
    # Filter by category/trnclass if provided
    filtered = {
        gid: g for gid, g in games.items()
        if not category or g.get("trnclass") == category
    }
    result = [build_game_response(gid, filtered[gid]) for gid in filtered]
    paged = result[start_idx: start_idx + max_results]
    return response({
        "total_results": len(result),
        "start_idx": start_idx,
        "max_results": max_results,
        "games": paged,
    })

@app.get("/game/{game_id}")
async def get_game(game_id: str, mgi_bearer_token: str = Header(None)):
    if game_id not in games:
        return response({"error": "game not found"}, 404)
    session = tokens.get(mgi_bearer_token)
    return response(build_game_response(game_id, games[game_id], viewer_session=session))

@app.post("/game/{game_id}/add_user")
async def add_user(game_id: str, req: dict = {}, mgi_bearer_token: str = Header(None)):
    if game_id not in games:
        return response({"error": "game not found"}, 404)
    if mgi_bearer_token not in tokens:
        return response({"error": "invalid token"}, 403)

    session = tokens[mgi_bearer_token]
    g = games[game_id]

    if len(g["players"]) >= g["max_players"]:
        return response({"error": "game full"}, 403)

    if session not in g["players"]:
        g["players"].append(session)

    mp_index = g["players"].index(session)
    return response({"game_id": game_id, "backend": generate_backend(mp_index)})

@app.post("/game/{game_id}/del_user")
async def leave_game(game_id: str, mgi_bearer_token: str = Header(None)):
    if game_id not in games:
        return response({"error": "game not found"}, 404)

    session = tokens.get(mgi_bearer_token)
    g = games[game_id]
    if session in g["players"]:
        g["players"].remove(session)

    if session == g.get("master_user_id"):
        if g["players"]:
            new_master = g["players"][0]
            g["master_user_id"] = new_master
            g["master_name"] = users.get(new_master, {}).get("name", "player")
        else:
            g["master_user_id"] = None
            g["master_name"] = None
            g["master_is_verified"] = False

    return response({"left": True, "backend": generate_backend(0)})

@app.post("/game/{game_id}/round/{round_id}/score")
async def post_score(game_id: str, round_id: str, req: dict):
    return response({"status": "score_received"})

# ---------------- LEADERBOARD ----------------
@app.post("/leaderboard")
async def leaderboard_post(req: dict):
    board = req.get("name", "default")
    score = req.get("score", 0)
    if board not in leaderboards:
        leaderboards[board] = []
    leaderboards[board].append(score)
    leaderboards[board].sort(reverse=True)
    return response({"status": "posted"})

@app.get("/leaderboard/{name}/{kind}")
async def leaderboard_get(name: str, kind: str, start_at: int = 0, count: int = 10):
    scores = leaderboards.get(name, [])
    entries = [
        {"rank": i + 1, "score": score, "user": "player"}
        for i, score in enumerate(scores[start_at: start_at + count])
    ]
    return response({
        "name": name,
        "kind": kind,
        "start_at": start_at,
        "count": count,
        "total_results": len(scores),
        "entries": entries,
    })

# ---------------- CHALLENGES ----------------
@app.get("/challenge/list")
async def challenge_list(limit: int = 6, published: str = "yes", full: str = "yes"):
    return response({"total_results": 0, "start_idx": 0, "max_results": limit, "challenges": []})

# ---------------- NEWSFEED ----------------
@app.get("/newsfeed/list")
async def newsfeed():
    return response({"items": []})

# ---------------- STATS ----------------
@app.get("/stats")
async def stats(category: str = ""):
    return response({"category": category, "stats": []})

# ---------------- TOURNAMENT ----------------
@app.get("/tournament/event_info/{release}/unified")
async def tournament_info(release: str):
    return response({
        "release": release,
        "active": [],
        "upcoming": [],
        "completed": [],
        "events": [],
    })