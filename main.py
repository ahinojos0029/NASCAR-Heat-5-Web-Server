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
        "platform_correlation_id": g.get("s.platform_correlation_id", ""),
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
        "enable_ai": bool_val(g.get("enable_ai", False)),
        "enable_chat": bool_val(g.get("enable_chat", True)),
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
    # Handle token similar to auth endpoint: treat invalid/placeholder tokens as requests for new sessions
    if not mgi_bearer_token or mgi_bearer_token.lower() in ["invalid", "none", ""]:
        token = str(uuid.uuid4())
    else:
        token = mgi_bearer_token

    if token not in tokens:
        session_id = str(uuid.uuid4())
        users[session_id] = {"created": time.time()}
        tokens[token] = session_id

    session = tokens[token]

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
        "enable_ai": bool_val(cfg.get("enable_ai", False)),
        "enable_chat": bool_val(cfg.get("enable_chat", True)),
        "num_laps": cfg.get("num_laps", 10),
        "league": cfg.get("league", "CUP"),
        "flags": cfg.get("flags", "NONE"),  # string
        "draft_influence": cfg.get("draft_influence", "MEDIUM"),  # string
        "stage_cfg": cfg.get("stage_cfg", [25, 25, 50]),  # list, will be JSON serialized in build_game_response
        "race_length": cfg.get("race_length", "LONG"),  # string
        "wear_factor": cfg.get("wear_factor", "NORMAL"),  # string
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
    request: Request,
    start_idx: int = 0,
    max_results: int = 200,
    category: str = ""
):
    # Get query parameters
    query_params = dict(request.query_params)
    requested_fields = query_params.getlist('val') if hasattr(query_params, 'getlist') else query_params.get('val', [])
    if isinstance(requested_fields, str):
        requested_fields = [requested_fields]

    filtered = {
        gid: g
        for gid, g in games.items()
        if not category or g.get("trnclass") == category
    }

    result = []
    for gid, g in filtered.items():
        game_response = build_game_response(gid, g)

        # If specific fields were requested, filter the response
        if requested_fields and len(requested_fields) > 0:
            filtered_response = {"id": gid}  # Always include ID
            for field in requested_fields:
                if field in game_response:
                    filtered_response[field] = game_response[field]
                # Handle nested fields like s.master_user_id
                elif '.' in field:
                    parts = field.split('.')
                    if len(parts) == 2 and parts[0] in game_response and parts[1] in game_response[parts[0]]:
                        if parts[0] not in filtered_response:
                            filtered_response[parts[0]] = {}
                        filtered_response[parts[0]][parts[1]] = game_response[parts[0]][parts[1]]
            result.append(filtered_response)
        else:
            result.append(game_response)

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
    # Handle token similar to auth endpoint: treat invalid/placeholder tokens as requests for new sessions
    if not mgi_bearer_token or mgi_bearer_token.lower() in ["invalid", "none", ""]:
        token = str(uuid.uuid4())
    else:
        token = mgi_bearer_token

    if token not in tokens:
        session_id = str(uuid.uuid4())
        users[session_id] = {"created": time.time()}
        tokens[token] = session_id

    session = tokens[token]

    if game_id not in games:
        return resp({"error": "game not found"}, 404)

    return resp(build_game_response(game_id, games[game_id], viewer_session=session))

@app.post("/game/{game_id}/add_user")
async def add_user(
    game_id: str,
    request: Request,
    mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")
):
    # Handle token similar to auth endpoint: treat invalid/placeholder tokens as requests for new sessions
    if not mgi_bearer_token or mgi_bearer_token.lower() in ["invalid", "none", ""]:
        token = str(uuid.uuid4())
    else:
        token = mgi_bearer_token

    if token not in tokens:
        session_id = str(uuid.uuid4())
        users[session_id] = {"created": time.time()}
        tokens[token] = session_id

    session = tokens[token]

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
    # Handle token similar to auth endpoint: treat invalid/placeholder tokens as requests for new sessions
    if not mgi_bearer_token or mgi_bearer_token.lower() in ["invalid", "none", ""]:
        token = str(uuid.uuid4())
    else:
        token = mgi_bearer_token

    if token not in tokens:
        session_id = str(uuid.uuid4())
        users[session_id] = {"created": time.time()}
        tokens[token] = session_id

    session = tokens[token]

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
    # Return some sample challenges
    challenges = [
        {
            "id": "challenge_001",
            "name": "Win 3 Races",
            "description": "Win 3 races in any mode",
            "icon": "win_races",
            "progress": 0,
            "target": 3,
            "reward": {
                "currency": 500,
                "xp": 250
            },
            "isDaily": True,
            "isWeekly": False,
            "isActive": True
        },
        {
            "id": "challenge_002",
            "name": "Lead a Lap",
            "description": "Lead at least one lap in a race",
            "icon": "lead_lap",
            "progress": 0,
            "target": 1,
            "reward": {
                "currency": 300,
                "xp": 150
            },
            "isDaily": True,
            "isWeekly": False,
            "isActive": True
        },
        {
            "id": "challenge_003",
            "name": "Podium Finisher",
            "description": "Finish in the top 3 in 5 races",
            "icon": "top_three",
            "progress": 0,
            "target": 5,
            "reward": {
                "currency": 1000,
                "xp": 500
            },
            "isDaily": False,
            "isWeekly": True,
            "isActive": True
        }
    ]

    # Filter by published status if needed
    if published.lower() == "no":
        challenges = [c for c in challenges if not c["isActive"]]

    # Limit results
    limited_challenges = challenges[:limit] if len(challenges) > limit else challenges

    return resp({
        "total_results": len(challenges),
        "start_idx": 0,
        "max_results": limit,
        "challenges": limited_challenges,
    })

# ---------------- NEWSFEED ----------------
@app.get("/newsfeed/list")
async def newsfeed():
    # Return some sample news items
    news_items = [
        {
            "id": "news_001",
            "header": "Welcome to NASCAR Heat 5 Online!",
            "hasImage": False,
            "priority": 1,
            "expiryDate": int(time.time()) + 86400 * 30,  # 30 days from now
            "sortedDate": int(time.time()),
            "type": "announcement",
            "link": ""
        },
        {
            "id": "news_002",
            "header": "New Weekend Event: Daytona Duel",
            "hasImage": False,
            "priority": 2,
            "expiryDate": int(time.time()) + 86400 * 7,  # 7 days from now
            "sortedDate": int(time.time()) - 86400,  # Yesterday
            "type": "event",
            "link": "/event/daytona_duel"
        }
    ]

    return resp({
        "items": news_items,
        "version": "1.0"
    })

# ---------------- STATS ----------------
@app.get("/stats")
async def stats(category: str = ""):
    # Return some sample stats based on category
    stats_data = []

    if category == "" or category == "N2020" or category == "general":
        stats_data = [
            {
                "statId": "total_races",
                "name": "Total Races",
                "value": 1250,
                "format": "integer"
            },
            {
                "statId": "wins",
                "name": "Wins",
                "value": 85,
                "format": "integer"
            },
            {
                "statId": "top_tens",
                "name": "Top 10 Finishes",
                "value": 320,
                "format": "integer"
            },
            {
                "statId": "poles",
                "name": "Pole Positions",
                "value": 12,
                "format": "integer"
            }
        ]
    elif category == "N2022":
        stats_data = [
            {
                "statId": "total_races",
                "name": "Total Races (2022)",
                "value": 420,
                "format": "integer"
            },
            {
                "statId": "wins",
                "name": "Wins (2022)",
                "value": 28,
                "format": "integer"
            }
        ]

    return resp({
        "category": category if category else "N2020",
        "stats": stats_data,
    })

# ---------------- TOURNAMENT ----------------
@app.get("/tournament/event_info/{release}/unified")
async def tournament_info(release: str):
    # Return some sample events based on the release
    events = []
    if release == "release-CUP":
        events = [
            {
                "eventId": "event_cup_001",
                "eventName": "Daytona 500 Qualifiers",
                "startTime": int(time.time()) - 86400,  # Yesterday
                "endTime": int(time.time()) + 86400 * 7,  # Next week
                "rewardId": "reward_cup_001",
                "isActive": True
            },
            {
                "eventId": "event_cup_002",
                "eventName": "Talladega Challenge",
                "startTime": int(time.time()) + 86400 * 2,  # In 2 days
                "endTime": int(time.time()) + 86400 * 9,  # Next week + 2 days
                "rewardId": "reward_cup_002",
                "isActive": False
            }
        ]
    elif release == "release-XFINITY":
        events = [
            {
                "eventId": "event_xfinity_001",
                "eventName": "Xfinity Series Opener",
                "startTime": int(time.time()) - 86400 * 2,
                "endTime": int(time.time()) + 86400 * 5,
                "rewardId": "reward_xfinity_001",
                "isActive": True
            }
        ]
    elif release == "release-TRUCK":
        events = [
            {
                "eventId": "event_truck_001",
                "eventName": "Truck Series Heat",
                "startTime": int(time.time()) - 86400,
                "endTime": int(time.time()) + 86400 * 3,
                "rewardId": "reward_truck_001",
                "isActive": True
            }
        ]
    elif release == "release-DIRT":
        events = [
            {
                "eventId": "event_dirt_001",
                "eventName": "Dirt Track Derby",
                "startTime": int(time.time()) - 86400 * 3,
                "endTime": int(time.time()) + 86400 * 4,
                "rewardId": "reward_dirt_001",
                "isActive": True
            }
        ]

    return resp({
        "release": release,
        "active": [e for e in events if e["isActive"]],
        "upcoming": [e for e in events if not e["isActive"] and e["startTime"] > int(time.time())],
        "completed": [e for e in events if not e["isActive"] and e["endTime"] < int(time.time())],
        "events": events,
    })