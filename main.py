from fastapi import FastAPI, Header, Request
from starlette.responses import Response

import uuid
import time
import socket
import json

# ---------------- RAW JSON ----------------
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
    headers["Content-Length"] = str(len(body))
    headers["Connection"] = "close"
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

# ---------------- HELPERS ----------------
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()
print(f"[SERVER] Local IP: {LOCAL_IP}")

def get_or_create_session(token):
    if not token or token.lower() in ["invalid", "none", "", "null", "undefined"]:
        token = str(uuid.uuid4())

    if token not in tokens:
        session_id = str(uuid.uuid4())
        users[session_id] = {
            "created": time.time(),
            "name": "player"
        }
        tokens[token] = session_id

    return token, tokens[token]

def generate_backend(session_index=0):
    return {
        "mpidx": session_index,
        "cipher": {"key": "localdevkey", "iv": "localiv"},
        "isn": {"send": 1, "recv": 1},
        "ip": LOCAL_IP,
    }

def build_game_response(gid, g, viewer_session=None):
    players = g.get("players", [])

    if viewer_session in players:
        session_index = players.index(viewer_session)
    else:
        session_index = 0

    return {
        "id": gid,
        "num_users": len(players),
        "max_users": g.get("max_players", 20),
        "has_password": False,
        "ping": 0,
        "region": "us",
        "build": "1.0",
        "joinable": True,

        "s": {
            "master_user_id": g.get("master_user_id") or "",
            "master_name": g.get("master_name") or "player",
            "master_is_verified": True,
            "state": g.get("state", 0),
            "friendly_state": g.get("friendly_state", "LOBBY"),
            "round_id": g.get("round_id") or str(uuid.uuid4()),
            "state_timeout": 0,
            "platform_session_id": "",
            "platform_correlation_id": "",
            "driving_backwards_rule": False,
            "trnclass": "N2020",
            "purpose": "RACE",
            "livedata_interval": 1000,
            "is_pro_mode": False,
            "min_users_for_scoring": 1,
        },

        "c": {
            "is_private": False,
            "force_sim_physics": False,
            "allow_custom_setups": False,
        },

        "race_length": g.get("race_length", 10),
        "num_laps": g.get("num_laps", 10),
        "wear_factor": 1.0,
        "flags": [],
        "event_id": "",
        "event_set_id": "",
        "session_type": "NORMAL",
        "damage": "FULL",
        "league": "CUP",
        "stage_cfg": [25, 25, 50],

        "enable_chat": True,
        "enable_ai": False,
        "friendly_track_name": "Daytona",
        "game_year": "PRESENT",
        "draft_influence": 1.0,

        "backend": generate_backend(session_index),
    }

async def parse_body(request: Request):
    try:
        body = await request.body()
        if body:
            return json.loads(body)
    except Exception as e:
        print("JSON parse failed:", e)
    return {}

# ---------------- AUTH ----------------
@app.get("/auth")
@app.post("/auth")
async def auth(request: Request, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    token, session_id = get_or_create_session(mgi_bearer_token)

    return raw_json({
        "session_id": session_id,
        "mgi_token": token,
        "backend": generate_backend(0)
    })

# ---------------- GAME ----------------
@app.post("/game")
async def create_game(request: Request, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    token, session = get_or_create_session(mgi_bearer_token)
    user = users.get(session, {})

    req = await parse_body(request)
    cfg = req.get("config", {})

    game_id = str(uuid.uuid4())

    g = {
        "players": [session],
        "max_players": 20,
        "state": 0,
        "friendly_state": "LOBBY",
        "round_id": str(uuid.uuid4()),
        "race_length": cfg.get("race_length", 10),
        "num_laps": cfg.get("num_laps", 10),
        "master_user_id": session,
        "master_name": user.get("name", "player"),
    }

    games[game_id] = g

    return raw_json(build_game_response(game_id, g, session))

@app.get("/game")
async def list_games():
    return raw_json({
        "total_results": len(games),
        "start_idx": 0,
        "max_results": 200,
        "games": [
            build_game_response(gid, g)
            for gid, g in games.items()
        ]
    })

@app.get("/game/{game_id}")
async def get_game(game_id: str, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    token, session = get_or_create_session(mgi_bearer_token)

    if game_id not in games:
        return raw_json(build_game_response("invalid", {"players": []}, session))

    return raw_json(build_game_response(game_id, games[game_id], session))

@app.post("/game/{game_id}/add_user")
async def add_user(game_id: str, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    token, session = get_or_create_session(mgi_bearer_token)

    if game_id not in games:
        return raw_json({"game_id": game_id, "backend": generate_backend(0)})

    g = games[game_id]

    if session not in g["players"]:
        g["players"].append(session)

    idx = g["players"].index(session)

    return raw_json({
        "game_id": game_id,
        "backend": generate_backend(idx)
    })

@app.post("/game/{game_id}/del_user")
async def leave_game(game_id: str, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    token, session = get_or_create_session(mgi_bearer_token)

    if game_id in games:
        g = games[game_id]
        if session in g["players"]:
            g["players"].remove(session)

    return raw_json({
        "left": True,
        "backend": generate_backend(0)
    })

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