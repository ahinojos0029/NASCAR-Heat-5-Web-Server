from fastapi import FastAPI, Header, Request
from starlette.responses import Response

import uuid
import time
import socket
import json

# ---------------- RAW JSON (ONLY RESPONSE PATH) ----------------
def raw_json(data, status=200):
    body = json.dumps(data, separators=(",", ":")).encode("utf-8")

    return Response(
        content=body,
        status_code=status,
        media_type="application/json",
        headers={
            "Content-Length": str(len(body)),
            "Connection": "close"
        }
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

def generate_backend(session_index=0):
    return {
        "mpidx": session_index,
        "cipher": {"key": "localdevkey", "iv": "localiv"},
        "isn": {"send": 1, "recv": 1},
        "ip": LOCAL_IP,
    }

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

def get_token_or_create(token):
    if not token or token.lower() in ["invalid", "none", ""]:
        token = str(uuid.uuid4())

    if token not in tokens:
        session_id = str(uuid.uuid4())
        users[session_id] = {"created": time.time()}
        tokens[token] = session_id

    return token, tokens[token]

# ---------------- AUTH ----------------
@app.get("/auth")
@app.post("/auth")
async def auth(request: Request, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    token, session_id = get_token_or_create(mgi_bearer_token)

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

# ---------------- USER ----------------
@app.post("/user")
async def create_user(request: Request):
    req = await parse_body(request)

    token = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    users[session_id] = {
        "created": time.time(),
        "name": req.get("name") or req.get("username") or "player"
    }

    tokens[token] = session_id

    return raw_json({
        "session_id": session_id,
        "mgi_token": token
    })

@app.get("/user/{user_id}")
async def get_user(user_id: str):
    if user_id not in users:
        return raw_json({"error": "user not found"}, 404)

    return raw_json({
        "id": user_id,
        "name": users[user_id].get("name", "player")
    })

@app.post("/user/config")
async def user_config():
    return raw_json({"status": "saved"})

# ---------------- GAME ----------------
def build_game_response(gid, g, viewer_session=None):
    players = g.get("players", [])
    idx = players.index(viewer_session) if viewer_session in players else 0

    return {
        "id": gid,
        "num_users": len(players),
        "max_users": g.get("max_players", 20),
        "joinable": True,
        "s": {
            "master_user_id": g.get("master_user_id"),
            "master_name": g.get("master_name", "host"),
            "state": g.get("state", 0),
        },
        "backend": generate_backend(idx)
    }

@app.post("/game")
async def create_game(request: Request, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    token, session = get_token_or_create(mgi_bearer_token)

    req = await parse_body(request)

    game_id = str(uuid.uuid4())

    games[game_id] = {
        "players": [session],
        "max_players": 20,
        "state": 0,
        "master_user_id": session,
        "master_name": users.get(session, {}).get("name", "player"),
    }

    return raw_json(build_game_response(game_id, games[game_id], session))

@app.get("/game")
async def list_games():
    return raw_json({
        "total_results": len(games),
        "games": [build_game_response(gid, g) for gid, g in games.items()]
    })

@app.get("/game/{game_id}")
async def get_game(game_id: str, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    if game_id not in games:
        return raw_json({"error": "game not found"}, 404)

    session = tokens.get(mgi_bearer_token)
    return raw_json(build_game_response(game_id, games[game_id], session))

@app.post("/game/{game_id}/add_user")
async def add_user(game_id: str, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    if game_id not in games:
        return raw_json({"error": "game not found"}, 404)

    token, session = get_token_or_create(mgi_bearer_token)
    g = games[game_id]

    if session not in g["players"]:
        g["players"].append(session)

    return raw_json({
        "game_id": game_id,
        "backend": generate_backend(g["players"].index(session))
    })

@app.post("/game/{game_id}/del_user")
async def leave_game(game_id: str, mgi_bearer_token: str = Header(None, alias="mgi-bearer-token")):
    if game_id not in games:
        return raw_json({"error": "game not found"}, 404)

    session = tokens.get(mgi_bearer_token)
    g = games[game_id]

    if session in g["players"]:
        g["players"].remove(session)

    return raw_json({"left": True, "backend": generate_backend(0)})

# ---------------- CHALLENGES ----------------
@app.get("/challenge/list")
async def challenge_list(limit: int = 6):
    return raw_json({
        "total_results": 0,
        "start_idx": 0,
        "max_results": limit,
        "challenges": []
    })

# ---------------- NEWS ----------------
@app.get("/newsfeed/list")
async def newsfeed():
    return raw_json({"items": []})

# ---------------- STATS ----------------
@app.get("/stats")
async def stats():
    return raw_json({"stats": []})

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