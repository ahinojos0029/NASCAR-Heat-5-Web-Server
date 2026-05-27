from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
import uuid
import time
a
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
users = {}
tokens = {}
games = {}
leaderboards = {}

# ---------------- HELPERS ----------------
def response(data, code=200):
    print(f"Returning JSON (status {code}):")
    import json
    print(json.dumps(data, indent=2))  # <-- add this
    r = JSONResponse(content=data)
    r.headers["ACTUAL-STATUS-CODE"] = str(code)
    return r

def generate_backend(session_index=0):
    """Generate a backend object compatible with JoinResponse.IsValid()"""
    return {
        "mpidx": session_index,
        "cipher": {"key": "localdevkey", "iv": "localiv"},
        "isn": {"send": 1, "recv": 1},
        "ip": "0.0.0.0"
    }
def build_game_response(gid, g):
    """Build a full game response including backend data"""
    if g["players"]:
        g["master_user_id"] = g.get("master_user_id") or g["players"][0]
        g["master_name"] = g.get("master_name") or "player"
        g["master_is_verified"] = g.get("master_is_verified", True)

    session_index = 0  # Default session index for backend
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
            "min_users_for_scoring": g["min_users_for_scoring"]
        },
        "c": {
            "is_private": g["is_private"],
            "force_sim_physics": g["force_sim_physics"],
            "allow_custom_setups": g["allow_custom_setups"]
        },
        "race_length": g["laps"],
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
        "backend": generate_backend(session_index)
    }

# ---------------- USER ----------------
@app.post("/user")
async def create_user(req: dict):
    session_id = str(uuid.uuid4())
    token = str(uuid.uuid4())
    users[session_id] = {"created": time.time()}
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
    return response({"id": user_id})

@app.post("/user/config")
async def user_config(req: dict):
    return response({"status": "saved"})

# ---------------- GAME ----------------
@app.post("/game")
async def create_game(req: dict = {}, mgi_bearer_token: str = Header(None)):
    if mgi_bearer_token not in tokens:
        return response({"error": "invalid token"}, 403)

    session = tokens[mgi_bearer_token]
    game_id = str(uuid.uuid4())
    g = {
        "players": [session],
        "max_players": req.get("backend", {}).get("capacity", 20),
        "state": 0,
        "friendly_state": "LOBBY",
        "round_id": str(uuid.uuid4()),
        "state_timeout": 0,
        "track": "SomeTrack",
        "track_name": "Some Track",
        "series": req.get("config", {}).get("league", "CUP"),
        "laps": 50,
        "num_laps": 50,
        "wear_factor": 1.0,
        "flags": [],
        "event_id": "event123",
        "event_set_id": req.get("config", {}).get("event_set_id", ""),
        "session_type": req.get("config", {}).get("session_type", "NORMAL"),
        "platform_session_id": str(uuid.uuid4()),
        "platform_correlation_id": str(uuid.uuid4()),
        "driving_backwards_rule": False,
        "is_private": req.get("config", {}).get("c.is_private", "false") == "true",
        "force_sim_physics": req.get("config", {}).get("c.force_sim_physics", "false") == "true",
        "allow_custom_setups": req.get("config", {}).get("c.allow_custom_setups", "false") == "true",
        "damage": "FULL",
        "league": req.get("config", {}).get("league", "CUP"),
        "stage_cfg": [],
        "enable_chat": req.get("config", {}).get("enable_chat", "false") == "true",
        "enable_ai": req.get("config", {}).get("enable_ai", "false") == "true",
        "trnclass": "N2020",
        "friendly_track_name": "Some Track",
        "game_year": req.get("config", {}).get("game_year", "PRESENT"),
        "purpose": "RACE",
        "livedata_interval": 1000,
        "is_pro_mode": False,
        "draft_influence": 1.0,
        "min_users_for_scoring": 1,
        "master_user_id": session,
        "master_name": "player",
        "master_is_verified": True
    }
    games[game_id] = g
    return response(build_game_response(game_id, g))

@app.get("/game")
async def list_games(start_idx: int = 0, max_results: int = 200, category: str = ""):
    result = [build_game_response(gid, games[gid]) for gid in games]
    return response({
        "total_results": len(result),
        "start_idx": start_idx,
        "max_results": max_results,
        "games": result
    })

@app.post("/game/{game_id}/add_user")
async def add_user(game_id: str, mgi_bearer_token: str = Header(None)):
    if game_id not in games:
        return response({"error": "game not found"}, 404)
    if mgi_bearer_token not in tokens:
        return response({"error": "invalid token"}, 403)

    session = tokens[mgi_bearer_token]
    g = games[game_id]
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

    # reassign master if needed
    if session == g.get("master_user_id"):
        if g["players"]:
            g["master_user_id"] = g["players"][0]
            g["master_name"] = "player"
        else:
            g["master_user_id"] = None
            g["master_name"] = None
            g["master_is_verified"] = True

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
    entries = [{"rank": i+1, "score": score, "user": "player"} for i, score in enumerate(scores[start_at:start_at+count])]
    return response({"name": name, "kind": kind, "start_at": start_at, "count": count, "entries": entries})

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
async def stats(category: str):
    return response({"category": category, "stats": []})

# ---------------- TOURNAMENT ----------------
@app.get("/tournament/event_info/{release}/unified")
async def tournament_info(release: str):
    return response({"release": release, "active": [], "upcoming": [], "completed": [], "events": []})