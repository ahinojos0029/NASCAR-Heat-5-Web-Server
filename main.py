from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

import uuid
import time
import socket
import json
import base64

def serialize_id(obj):
    """Serialize an object to a base64-encoded JSON string (matches Unity's NgUtil.SerializeId)"""
    json_str = json.dumps(obj, separators=(',', ':'))
    return base64.b64encode(json_str.encode('utf-8')).decode('utf-8')

def deserialize_id(b64_str):
    """Deserialize a base64-encoded JSON string (matches Unity's NgUtil.DeserializeId)"""
    try:
        json_str = base64.b64decode(b64_str).decode('utf-8')
        return json.loads(json_str)
    except Exception:
        return None

def raw_json(data, status=200):
    body = json.dumps(data, separators=(",", ":")).encode("utf-8")

    return Response(
        content=body,
        status_code=status,
        media_type="application/json"
    )

app = FastAPI(debug=False)

# ---------------- MIDDLEWARE ----------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"\n----- {request.method} {request.url.path} -----")
    print("Headers:", dict(request.headers))

    response = await call_next(request)

    body = b""
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, bytes) else chunk.encode()

    headers = dict(response.headers)

    headers["ACTUAL-STATUS-CODE"] = str(response.status_code)
    headers["Content-Length"] = str(len(body))
    headers["Connection"] = "close"

    # 🔥 kill chunked encoding
    headers.pop("transfer-encoding", None)

    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type
    )

# ---------------- DATA ----------------
users = {}
tokens = {}
games = {}
leaderboards = {}

# ---------------- HELPERS ----------------
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

print(f"[SERVER] Local IP: {LOCAL_IP}")

def resp(data, code=200):
    print(f"Returning JSON ({code}):")
    print(json.dumps(data, indent=2))

    return JSONResponse(
        content=data,
        status_code=code,
        headers={
            "Connection": "close"
        }
    )

def generate_backend(session_index=0):
    return {
        "mpidx": session_index,
        "cipher": {
            "key": "localdevkey",
            "iv": "localiv"
        },
        "isn": {
            "send": 1,
            "recv": 1
        },
        "ip": "zephyr.proxy.rlwy.net",
    }

def build_game_response(gid, g, viewer_session=None):
    players = g.get("players", [])

    if viewer_session in players:
        session_index = players.index(viewer_session)
    else:
        session_index = 0

    # Build the s object (session fields)
    s_obj = {
        "master_user_id": g.get("s.master_user_id", ""),
        "master_name": g.get("s.master_name", "host"),
        "master_is_verified": g.get("s.master_is_verified", True),
        "platform_session_id": g.get("s.platform_session_id", ""),
        "s.platform_correlation_id": g.get("s.platform_correlation_id", ""),
        "driving_backwards_rule": g.get("s.driving_backwards_rule", False),
        "state": g.get("s.state", "lobby"),  # string: "lobby", "load_and_sync", "racing", "postrace"
        "friendly_state": g.get("s.friendly_state", "LOBBY"),
        "round_id": g.get("s.round_id", str(uuid.uuid4())),
        "state_timeout": g.get("s.state_timeout", 0),
        "livedata_interval": g.get("s.livedata_interval", 1000),
        "is_pro_mode": g.get("s.is_pro_mode", False),
        "min_users_for_scoring": g.get("s.min_users_for_scoring", 1),
        "purpose": g.get("s.purpose", "RACE"),
        "trnclass": g.get("s.trnclass", "N2020")
    }

    # Build the c object (config fields)
    c_obj = {
        "is_private": g.get("c.is_private", False),
        "force_sim_physics": g.get("c.force_sim_physics", False),
        "allow_custom_setups": g.get("c.allow_custom_setups", False)
    }

    # Build the top-level game fields
    game_obj = {
        "id": gid,
        "s": s_obj,
        "c": c_obj,
        "enable_ai": g.get("enable_ai", False),
        "enable_chat": g.get("enable_chat", True),
        "num_laps": g.get("num_laps", 10),
        "league": g.get("league", "CUP"),
        "flags": g.get("flags", "NONE"),  # string
        "stage_cfg": json.dumps(g.get("stage_cfg", [25, 25, 50])),  # JSON string
        "race_length": g.get("race_length", "LONG"),  # string
        "wear_factor": g.get("wear_factor", "NORMAL"),  # string
        "draft_influence": g.get("draft_influence", "MEDIUM"),  # string
        "event_id": g.get("event_id", serialize_id({"id": str(uuid.uuid4())})),  # base64-encoded JSON
        "event_set_id": g.get("event_set_id", serialize_id({"id": str(uuid.uuid4())})),  # base64-encoded JSON
        "session_type": g.get("session_type", "NORMAL"),
        "game_year": g.get("game_year", "PRESENT"),
        "friendly_track_name": g.get("friendly_track_name", "Daytona"),
        "damage": g.get("damage", "FULL"),
        # Legacy fields from the original implementation (keep for compatibility)
        "num_users": len(players),
        "max_users": g.get("max_players", 20),
        "has_password": False,
        "ping": 0,
        "region": "us",
        "build": "1.0",
        "joinable": True,
        "backend": generate_backend(session_index)
    }

    return game_obj

async def parse_body(request: Request):
    try:
        body = await request.body()

        if body:
            return json.loads(body)

    except Exception as e:
        print("JSON parse failed:", e)

    return {}

def bool_val(v, default=False):
    if v is None:
        return default

    if isinstance(v, bool):
        return v

    return str(v).lower() == "true"

# ---------------- USER ----------------
def register_token(
    token,
    platform="unknown",
    name="player",
    version="",
    client_version=""
):
    if token not in tokens:
        session_id = str(uuid.uuid4())

        users[session_id] = {
            "created": time.time(),
            "platform": platform,
            "name": name,
            "version": version,
            "client_version": client_version,
            # User fields expected by Unity NGUtil.UserSessionInfo2NetGameUserInfo
            "s.name": name,
            "s.platform_user_id": "",  # We don't have platform-specific ID
            "s.sort_val": 0.0,         # Default sort value (valid float)
            "s.is_verified": False,    # Not verified by default
            "user_driver": serialize_id({}),  # Empty PersonaId as base64 JSON
            "appearance_id": serialize_id({}), # Empty CarAppearanceId as base64 JSON
            "jingle": "",
            "rolling_points": 0,
        }

        tokens[token] = session_id

    return tokens[token]

PLACEHOLDER_TOKENS = {
    "invalid",
    "none",
    "null",
    "",
    "undefined"
}

def is_placeholder(token):
    return not token or token.lower() in PLACEHOLDER_TOKENS

# ---------------- AUTH ----------------
def get_token_or_403(mgi_bearer_token: str):
    if not mgi_bearer_token or mgi_bearer_token not in tokens:
        return None
    return tokens[mgi_bearer_token]


@app.get("/auth")
@app.post("/auth")
async def auth(request: Request, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    # ONLY place where tokens are created
    if not mgi_bearer_token or mgi_bearer_token.lower() in ["invalid", "none", ""]:
        token = str(uuid.uuid4())
    else:
        token = mgi_bearer_token

    if token not in tokens:
        session_id = str(uuid.uuid4())
        users[session_id] = {"created": time.time()}
        tokens[token] = session_id

    session_id = tokens[token]

    return raw_json({
        "session_id": session_id,
        "mgi_token": token,
        "backend": {
            "mpidx": 0,
            "ip": LOCAL_IP,
            "cipher": {"key": "localdevkey", "iv": "localiv"},
            "isn": {"send": 1, "recv": 1}
        }
    })

@app.post("/user")
async def create_user(request: Request):
    req = await parse_body(request)

    token = str(uuid.uuid4())

    session_id = register_token(
        token,
        platform=req.get("platform", "unknown"),
        name=req.get("name") or req.get("username") or "player",
        version=req.get("version", ""),
        client_version=req.get("client_version", ""),
    )

    return resp({
        "session_id": session_id,
        "mgi_token": token
    })

@app.get("/user/{user_id}")
async def get_user(user_id: str):
    if user_id not in users:
        return resp({
            "error": "user not found"
        }, 404)

    u = users[user_id]

    return resp({
        "id": user_id,
        "name": u.get("name", "player")
    })

@app.post("/user/config")
async def user_config(request: Request):
    return resp({
        "status": "saved"
    })

# ---------------- GAME ----------------
@app.post("/game")
async def create_game(
    request: Request,
    mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")
):
    session = get_token_or_403(mgi_bearer_token)
    if not session:
        return resp({"error": "invalid token"}, 403)

    user = users.get(session, {})

    req = await parse_body(request)
    cfg = req.get("config", {})
    # backend_cfg is not used currently

    game_id = str(uuid.uuid4())

    # Generate default values for the game session
    # We'll store the game data in the format expected by the new build_game_response
    g = {
        # Session fields (with 's.' prefix)
        "s.master_user_id": session,
        "s.master_name": user.get("s.name", "player"),
        "s.master_is_verified": True,
        "s.platform_session_id": "",  # We don't have platform session ID
        "s.platform_correlation_id": "", # We don't have platform correlation ID
        "s.driving_backwards_rule": False, # Default to false
        "s.state": "lobby",  # Start in lobby (string)
        "s.friendly_state": "LOBBY",
        "s.round_id": str(uuid.uuid4()),
        "s.state_timeout": 0,
        "s.livedata_interval": 1000,
        "s.is_pro_mode": False,
        "s.min_users_for_scoring": 1,
        "s.purpose": "RACE",
        "s.trnclass": cfg.get("trnclass", "N2020"),  # Tournament class from config

        # Config fields (with 'c.' prefix)
        "c.is_private": cfg.get("is_private", False),
        "c.force_sim_physics": cfg.get("force_sim_physics", False),
        "c.allow_custom_setups": cfg.get("allow_custom_setups", False),

        # Top-level game fields
        "enable_ai": cfg.get("enable_ai", False),
        "enable_chat": cfg.get("enable_chat", True),
        "num_laps": cfg.get("num_laps", 10),
        "league": cfg.get("league", "CUP"),
        "flags": cfg.get("flags", "NONE"),  # string
        "stage_cfg": cfg.get("stage_cfg", [25, 25, 50]),  # list, will be JSON serialized in build_game_response
        "race_length": cfg.get("race_length", "LONG"),  # string
        "wear_factor": cfg.get("wear_factor", "NORMAL"),  # string
        "draft_influence": cfg.get("draft_influence", "MEDIUM"),  # string
        "event_id": serialize_id({"id": str(uuid.uuid4())}),  # Base64-encoded JSON
        "event_set_id": serialize_id({"id": str(uuid.uuid4())}), # Base64-encoded JSON
        "session_type": cfg.get("session_type", "NORMAL"),
        "game_year": cfg.get("game_year", "PRESENT"),
        "friendly_track_name": cfg.get("friendly_track_name", "Daytona"),
        "damage": cfg.get("damage", "FULL"),
        # Note: damage_mode is duplicate of damage in the Unity code? We'll set it the same.
        "damage_mode": cfg.get("damage", "FULL"),
        # Players and max_players
        "players": [session],
        "max_players": 20  # default, could be made configurable
    }

    games[game_id] = g

    # For the response, we need to build the game response for the creator (viewer_session = session)
    return resp(build_game_response(game_id, g, viewer_session=session))

@app.get("/game")
async def list_games(
    start_idx: int = 0,
    max_results: int = 200,
    category: str = ""
):
    filtered = {
        gid: g
        for gid, g in games.items()
        if not category or g.get("trnclass") == category
    }

    result = [
        build_game_response(gid, filtered[gid])
        for gid in filtered
    ]

    paged = result[start_idx:start_idx + max_results]

    return resp({
        "total_results": len(result),
        "start_idx": start_idx,
        "max_results": max_results,
        "games": paged,
    })

@app.get("/game/{game_id}")
async def get_game(
    game_id: str,
    mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")
):
    if game_id not in games:
        return resp({"error": "game not found"}, 404)

    session = tokens.get(mgi_bearer_token)

    return resp(build_game_response(game_id, games[game_id], viewer_session=session))

@app.post("/game/{game_id}/add_user")
async def add_user(
    game_id: str,
    request: Request,
    mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")
):
    session = get_token_or_403(mgi_bearer_token)
    if not session:
        return resp({"error": "invalid token"}, 403)

    if game_id not in games:
        return resp({"error": "game not found"}, 404)

    g = games[game_id]

    if session not in g["players"]:
        if len(g["players"]) >= g["max_players"]:
            return resp({"error": "game full"}, 403)

        g["players"].append(session)

    mp_index = g["players"].index(session)

    return resp({
        "game_id": game_id,
        "backend": generate_backend(mp_index)
    })

@app.post("/game/{game_id}/del_user")
async def leave_game(
    game_id: str,
    mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")
):
    session = get_token_or_403(mgi_bearer_token)
    if not session:
        return resp({"error": "invalid token"}, 403)

    if game_id not in games:
        return resp({"error": "game not found"}, 404)

    g = games[game_id]

    if session in g["players"]:
        g["players"].remove(session)

    return resp({"left": True, "backend": generate_backend(0)})

@app.post("/game/{game_id}/round/{round_id}/score")
async def post_score(game_id: str, round_id: str, request: Request):
    return resp({"status": "score_received"})

# ---------------- LEADERBOARD ----------------
@app.post("/leaderboard")
async def leaderboard_post(request: Request):
    req = await parse_body(request)
    board = req.get("name", "default")
    score = req.get("score", 0)
    if board not in leaderboards:
        leaderboards[board] = []
    leaderboards[board].append(score)
    leaderboards[board].sort(reverse=True)
    return resp({"status": "posted"})

@app.get("/leaderboard/{name}/{kind}")
async def leaderboard_get(name: str, kind: str, start_at: int = 0, count: int = 10):
    scores = leaderboards.get(name, [])
    entries = [
        {"rank": i + 1, "score": score, "user": "player"}
        for i, score in enumerate(scores[start_at: start_at + count])
    ]
    return resp({
        "name":          name,
        "kind":          kind,
        "start_at":      start_at,
        "count":         count,
        "total_results": len(scores),
        "entries":       entries,
    })

# ---------------- CHALLENGES ----------------
@app.get("/challenge/list")
async def challenge_list(limit: int = 6, published: str = "yes", full: str = "yes"):
    return resp({"total_results": 0, "start_idx": 0, "max_results": limit, "challenges": []})

# ---------------- NEWSFEED ----------------
@app.get("/newsfeed/list")
async def newsfeed():
    return resp({"items": []})

# ---------------- STATS ----------------
@app.get("/stats")
async def stats(category: str = ""):
    return resp({"category": category, "stats": []})

# ---------------- TOURNAMENT ----------------
@app.get("/tournament/event_info/{release}/unified")
async def tournament_info(release: str):
    return resp({
        "release":   release,
        "active":    [],
        "upcoming":  [],
        "completed": [],
        "events":    [],
    })