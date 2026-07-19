# app.py – NASCAR Heat 5 emulator (Flask) that works with UnityWebRequest
# ----------------------------------------------------------------------
# * Prints request/response details to stdout (visible in Railway logs)
# * Always returns JSON with correct Content-Type
# * Guarantees HTTP 200 status (errors are reported inside JSON)
# * Adds the ACTUAL-STATUS-CODE header that Unity expects
# * Accepts any MGI-Bearer-Token (creates a temporary session if needed)
# * Reads $PORT from the environment (Railway, localhost, etc.)
# ----------------------------------------------------------------------

import os
import sys
import uuid
import random
import socket
import threading
from flask import Flask, request, jsonify

app = Flask(__name__)

# ----------------------------------------------------------------------
# UDP Multiplayer Connection State
# ----------------------------------------------------------------------

class HeatConnection:
    def __init__(self, user_id):
        self.user_id = user_id

        # Connection state
        self.state = "WAIT_CONNECT"

        # Packet counters
        self.recv_seq = 0
        self.send_seq = 0

        # Initial sequence numbers from JoinResponse
        self.srv_seq = 0
        self.cli_seq = 0

        # UDP endpoint
        self.addr = None

        # Last received packet
        self.last_packet = None

        # Crypto information
        # Filled during /add_user
        self.cipher = None

        # Client handshake data
        # Filled when first UDP packet arrives
        self.client_iv = None
        self.client_suffix = None
        self.client_payload = None


udp_connections = {}
heat_connections = {}

# ----------------------------------------------------------------------
# UDP Multiplayer Packet Logger
# ----------------------------------------------------------------------

def udp_logger():
    global udp_resp

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 7777))

    print("UDP LOGGER STARTED")
    sys.stdout.flush()

    while True:
        try:
            data, addr = sock.recvfrom(4096)

            print("\n========== UDP PACKET ==========")
            print("FROM:", addr)
            print("SIZE:", len(data))


            # --------------------------------------------------
            # Find existing Heat connection
            # --------------------------------------------------

            active_connection = None

            for uid, heat_conn in udp_connections.items():

                if heat_conn.addr == addr:
                    active_connection = heat_conn
                    break


            # --------------------------------------------------
            # Assign new UDP packet to waiting connection
            # --------------------------------------------------

            if active_connection is None:

                for uid, heat_conn in udp_connections.items():

                    if heat_conn.addr is None:

                        heat_conn.addr = addr
                        heat_conn.state = "CONNECTED"

                        active_connection = heat_conn

                        print("\nASSIGNED UDP CONNECTION")
                        print("USER:", uid)
                        print("ADDRESS:", addr)

                        break

            if active_connection:

                active_connection.recv_seq += 1
                active_connection.last_packet = data

                # Store client handshake values
                if len(data) >= 112:

                    client_iv = data[:16]

                    client_payload = data[16:80]

                    client_suffix = data[-32:]

                    print("\nCLIENT HANDSHAKE DATA")
                    print("CLIENT IV:", client_iv.hex())
                    print("CLIENT SUFFIX:", client_suffix.hex())

                    active_connection.client_iv = client_iv
                    active_connection.client_suffix = client_suffix
                    active_connection.client_payload = client_payload

            # --------------------------------------------------
            # Packet dump
            # --------------------------------------------------

            print("\nFULL HEX:")
            print(data.hex())

            print("\nPART 1 - FIRST 16 BYTES (Possible IV):")
            print(data[:16].hex())

            print("\nPART 2 - MIDDLE DATA (Encrypted Payload):")
            print(data[16:-32].hex())

            print("\nPART 3 - LAST 32 BYTES (Connection Suffix):")
            print(data[-32:].hex())


            print("\nBYTE LIST:")
            print(list(data))


            # --------------------------------------------------
            # Send Crypto handshake response
            # --------------------------------------------------

            print("\nCurrent UDP RESPONSE:")

            if (
                active_connection is not None
                and hasattr(active_connection, "udp_response")
                and active_connection.udp_response is not None
            ):

                response = active_connection.udp_response

                print(response.hex())

                sock.sendto(
                    response,
                    addr
                )

                active_connection.send_seq += 1

                print("\nSENT RESP_MESSAGE:")
                print(response.hex())

            else:

                print("None")
                print("\nNO UDP RESPONSE AVAILABLE")

            print("\n===============================\n")

            sys.stdout.flush()

        except Exception as e:

            print("UDP ERROR:", e)
            sys.stdout.flush()

# ----------------------------------------------------------------------
# Simple helper to flush logs immediately (Works with Gunicorn)
# ----------------------------------------------------------------------
def _log(msg: str) -> None:
    """Write a line to stdout and flush so it appears in Railway logs instantly."""
    try:
        print(msg)
        sys.stdout.flush()
    except Exception:
        # Ignore logging errors to prevent crashing the app
        pass

# ----------------------------------------------------------------------
# UDP Multiplayer Connection State
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# In-memory stores
# ----------------------------------------------------------------------
sessions = {}
users = {}
games = {}
connections = {}

# UDP handshake response (set during add_user)
udp_resp = None

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
challenges = []
stats_values = {}

# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------

def make_bytes(size):
    """
    Creates random byte arrays for CryptoDLL.StaticConnectionData.
    """
    return list(os.urandom(size))


def make_token():    return str(uuid.uuid4())
def make_session_id(): return str(uuid.uuid4())
def make_user_id():    return str(uuid.uuid4())
def make_game_id():    return f"game_{len(games) + 1}"

def json_response(data, status_code=200):
    """
    Returns a Flask Response that:
      * has application/json Content‑Type
      * carries ACTUAL-STATUS-CODE header (always 200 for the client)
      * contains JSON‑serialized *data*
    The *status_code* argument is kept for internal use but the
    outgoing HTTP status is forced to 200 so Unity never sees an error.
    """
    resp = jsonify(data)
    resp.status_code = 200                     # Force 200 for Unity
    resp.headers["Content-Type"] = "application/json"
    resp.headers["ACTUAL-STATUS-CODE"] = "200" # Unity reads this header
    return resp

def require_auth():
    """
    Validate MGI-Bearer‑Token.
    For the emulator we accept any token (including "invalid" or missing)
    and create a temporary session/user if needed.
    Returns the session dict: {"session_id":..., "user_id":...}
    """
    token = request.headers.get("MGI-Bearer-Token")
    if token in sessions:
        return sessions[token]

    # Token not known – create a temporary user/session so the call succeeds
    user_id = make_user_id()
    session_id = make_session_id()
    sessions[token] = {"session_id": session_id, "user_id": user_id}
    # Provide a minimal user record so later look‑ups work
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
        "badge": {},
    }
    return sessions[token]

# ----------------------------------------------------------------------
# Request / Response logging (visible in Railway logs)
# ----------------------------------------------------------------------

@app.before_request
def log_every_request():
    print("\n>>>", request.method, request.path)

    if request.args:
        print("ARGS:", dict(request.args))

    if request.data:
        print("BODY:", request.data.decode("utf-8"))

@app.after_request
def _log_response(response):
    try:
        data = response.get_data()
        data_preview = (
            data[:200].decode('utf-8', errors='replace')
            if data else ''
        )
        _log(
            f"<<< {response.status} {response.status_code}\n"
            f"Headers: {dict(response.headers)}\n"
            f"Body ({len(data)} bytes): {data_preview}"
        )
    except Exception as e:
        _log(f"!!! Error in _log_response: {e}")
    return response

# ----------------------------------------------------------------------
# Generic error handler – always return JSON inside a 200 response
# ----------------------------------------------------------------------
@app.errorhandler(Exception)
def handle_all_errors(e):
    _log(f"!!! Unhandled exception: {e}")
    try:
        # Return a 200 response with an error flag so the client can still parse JSON.
        return json_response({"error": str(e)}), 200
    except Exception as e2:
        _log(f"!!! Error in error handler: {e2}")
        return json_response({"error": "Internal server error"}), 200

# ----------------------------------------------------------------------
# AUTHENTICATION
# ----------------------------------------------------------------------
@app.route("/user", methods=["POST"])
def create_user():
    """
    Request: UserSessionCreateResponse
    Response: { "session_id": "...", "mgi_token": "..." }
    """
    payload = request.get_json(silent=True) or {}
    _ = payload  # fields are not needed for the emulator
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
        "badge": {},
    }
    sessions[token] = {"session_id": session_id, "user_id": user_id}
    return json_response({"session_id": session_id, "mgi_token": token})

@app.route("/auth", methods=["GET"])
def auth():
    """EmptyResponse – the game only checks that we return 200."""
    return json_response({})

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
    payload = request.get_json(silent=True) or {}
    games[game_id]["reservations"] = payload.get("count", 0)
    return json_response({})

@app.route("/game", methods=["POST"])
def create_game():
    """
    Expected request: GameSessionCreateRequest
    Expected response: { "id": "<new‑game‑id>" }
    """
    payload = request.get_json(silent=True) or {}
    gid = make_game_id()
    games[gid] = {
        "config": payload.get("config", {}),
        "users": set(),
        "reservations": 0,
        "scores": {}
    }
    return json_response({"id": gid})

@app.route("/game/<game_id>/add_user", methods=["POST"])
def add_user(game_id):

    request_body = request.get_json(silent=True) or {}

    print("\n========== ADD USER ==========")
    print("Game:", game_id)
    print("Request:", request_body)

    sess = require_auth()
    user_id = sess["user_id"]

    if game_id not in games:
        games[game_id] = {
            "config": {},
            "users": set(),
            "reservations": 0,
            "scores": {}
        }

    games[game_id]["users"].add(user_id)

    # Assign multiplayer index
    mpidx = len(games[game_id]["users"]) - 1


    # --------------------------------------------------
    # Generate crypto connection data
    # --------------------------------------------------

    cipher = {
        "iv": make_bytes(16),
        "aes_key": make_bytes(32),
        "hmac_key": make_bytes(32),
        "conn_suffix": make_bytes(32),
        "conn_message": make_bytes(32),
        "resp_message": make_bytes(64)
    }


    # Initial sequence numbers
    isn = {
        "srv_seq": random.randint(10000, 0x7FFFFFFF),
        "cli_seq": random.randint(10000, 0x7FFFFFFF),
    }


    # HTTP connection information
    connection = {
        "game_id": game_id,
        "user_id": user_id,
        "mpidx": mpidx,
        "cipher": cipher,
        "isn": isn,
        "ip": "10.0.0.39:7777",
        "port": 7777
    }


    # --------------------------------------------------
    # Create UDP connection state
    # --------------------------------------------------

    conn = HeatConnection(user_id)

    # Store crypto information
    conn.cipher = cipher

    # Store sequence numbers
    conn.srv_seq = isn["srv_seq"]
    conn.cli_seq = isn["cli_seq"]


    print("\nHEAT CONNECTION CREATED")
    print("USER:", conn.user_id)
    print("SRV SEQ:", conn.srv_seq)
    print("CLI SEQ:", conn.cli_seq)
    print("CIPHER STORED:", conn.cipher is not None)


    # Store the SAME object everywhere
    connections[user_id] = connection
    heat_connections[user_id] = conn
    udp_connections[user_id] = conn



    # --------------------------------------------------
    # Wait for UDP handshake
    # --------------------------------------------------

    global udp_resp

    udp_resp = None

    print("\nUDP RESPONSE WAITING FOR CLIENT PACKET")



    print("\nCreated connection:")
    print(connection)


    print("\nHEAT CONNECTION STATE:")
    print("USER:", conn.user_id)
    print("STATE:", conn.state)
    print("SRV SEQ:", conn.srv_seq)
    print("CLI SEQ:", conn.cli_seq)



    response = {
        "game_id": game_id,
        "backend": {
            "error": {
                "sc": 0,
                "description": "",
                "error": "",
                "show": False,
                "no_mp": False,
                "log_in_again": False
            },
            "mpidx": mpidx,
            "cipher": cipher,
            "isn": isn,
            "ip": "10.0.0.39:7777"
        }
    }


    print("\nSending JoinResponse:")
    print(response)
    print("==============================\n")


    return json_response(response)

@app.route("/game/<game_id>", methods=["POST"])
def set_game_info(game_id):
    if game_id not in games:
        games[game_id] = {"config":{}, "users":set(), "reservations":0, "scores":{}}
    payload = request.get_json(silent=True) or {}
    games[game_id]["config"].update(payload.get("config", {}))
    return json_response({})

@app.route("/game/<game_id>/op/<op>", methods=["POST"])
def game_op(game_id, op):

    payload = request.get_json(silent=True) or {}

    _log("\n========== GAME OP ==========")
    _log(f"Game: {game_id}")
    _log(f"Operation: {op}")
    _log(f"Payload: {payload}")
    _log("=============================\n")

    if game_id in games:
        games[game_id]["last_op"] = op

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

    _log("========== PARTICIPANTS REQUEST ==========")
    _log(f"Game: {game_id}")
    _log(f"Round: {round_id}")
    _log("==========================================")

    if game_id not in games:
        return json_response({"users": []})

    sess = require_auth()
    local_user_id = sess["user_id"]

    user_list = []

    for idx, uid in enumerate(games[game_id]["users"]):
        u = users.get(uid, {})

        try:
            sort_val = float(u.get("sortVal", 0.0))
        except (ValueError, TypeError):
            sort_val = 0.0

        try:
            roll_points = int(u.get("rollingPoints", 0))
        except (ValueError, TypeError):
            roll_points = 0

        user_info = {
            "userId": uid,
            "isLocalUser": (uid == local_user_id),
            "mpIdx": idx,
            "name": u.get("name", "Player"),
            "platformUserId": u.get("platformUserId", ""),
            "sortVal": sort_val,
            "isVerified": u.get("isVerified", False),
            "basePersonaId": u.get("basePersonaId", ""),
            "appearanceId": u.get("appearanceId", ""),
            "jingle": u.get("jingle", ""),
            "rollingPoints": roll_points,
            "badge": u.get("badge", {})
        }

        user_list.append(user_info)

    _log(f"Returning {len(user_list)} participants")
    _log(f"Participants: {user_list}")
    _log("==========================================")

    return json_response({"users": user_list})
@app.route("/game/<game_id>/users", methods=["GET"])
def users_in_game(game_id):
    return participants(game_id, "0")

@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    if user_id not in users:
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
            "badge": {},
        }
    else:
        u = users[user_id]
    try:
        sort_val = float(u.get("sortVal", 0.0))
    except (ValueError, TypeError):
        sort_val = 0.0
    try:
        roll_points = int(u.get("rollingPoints", 0))
    except (ValueError, TypeError):
        roll_points = 0
    resp = {
        "userId": u.get("userId", user_id),
        "isLocalUser": u.get("isLocalUser", False),
        "mpIdx": u.get("mpIdx", 0),
        "name": u.get("name", "Player"),
        "platformUserId": u.get("platformUserId", ""),
        "sortVal": sort_val,
        "isVerified": u.get("isVerified", False),
        "basePersonaId": u.get("basePersonaId", ""),
        "appearanceId": u.get("appearanceId", ""),
        "jingle": u.get("jingle", ""),
        "rollingPoints": int(roll_points),  # already int, but safe
        "badge": u.get("badge", {}),
    }
    return json_response(resp)

@app.route("/user/config", methods=["POST"])
def set_user_info():
    sess = require_auth()
    user_id = sess["user_id"]
    payload = request.get_json(silent=True) or {}
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
            "badge": {},
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
    payload = request.get_json(silent=True) or {}
    event = {
        "lapData": payload.get("data"),
        "raceTimeData": payload.get("racetime_data")
    }
    games[game_id]["scores"].setdefault(round_id, []).append(event)
    return json_response({})

# ----------------------------------------------------------------------
# INVITATIONS
# ----------------------------------------------------------------------
@app.route("/invitation/consume", methods=["POST"])
def consume_invitation():
    payload = request.get_json(silent=True) or {}
    return json_response({})

@app.route("/invitation/send", methods=["POST"])
def invite_bunch():
    payload = request.get_json(silent=True) or {}
    return json_response({})

# ----------------------------------------------------------------------
# TELEMETRY
# ----------------------------------------------------------------------
@app.route("/info/connection", methods=["POST"])
def report_connection():
    payload = request.get_json(silent=True) or {}
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
    return json_response({"error": "not found"}), 200   # still 200 so Unity stays happy

# ----------------------------------------------------------------------
# ANALYTICS
# ----------------------------------------------------------------------
@app.route("/analytics/postrace", methods=["POST"])
def post_race_analytics():
    payload = request.get_json(silent=True) or {}
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
    payload = request.get_json(silent=True) or {}
    posts = payload.get("posts", [])
    lb_name = "global"
    leaderboards.setdefault(lb_name, []).extend(posts)
    return json_response({"entries": leaderboards[lb_name][-len(posts):],
                          "total": len(leaderboards[lb_name])})

@app.route("/leaderboard/advance_time", methods=["POST"])
def advance_leaderboard_time():
    payload = request.get_json(silent=True) or {}
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
    return json_response([])   # wrapper expects a list

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
    payload = request.get_json(silent=True) or {}
    return json_response({"entries": []})

# ----------------------------------------------------------------------
# DEBUG: Catch unknown Heat 5 requests
# ----------------------------------------------------------------------
@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","DELETE"])
@app.route("/<path:path>", methods=["GET","POST","PUT","DELETE"])
def catch_all(path):

    _log("\n========== UNKNOWN REQUEST ==========")
    _log(f"METHOD: {request.method}")
    _log(f"PATH: /{path}")

    if request.args:
        _log(f"ARGS: {dict(request.args)}")

    if request.data:
        _log(
            "BODY: " +
            request.data.decode("utf-8", errors="ignore")
        )

    _log("====================================\n")

    return json_response({})

@app.errorhandler(404)
def not_found(e):
    print("\n!!! UNKNOWN ENDPOINT !!!")
    print(request.method, request.path)
    print(request.data.decode("utf-8", errors="ignore"))
    print("========================\n")

    return "{}", 200

# ----------------------------------------------------------------------
# RUN – read PORT from the environment (Railway uses $PORT)
# ----------------------------------------------------------------------
if __name__ == "__main__":

    # Start Heat 5 UDP multiplayer listener
    udp_thread = threading.Thread(
        target=udp_logger,
        daemon=True
    )

    udp_thread.start()

    port = int(os.environ.get("PORT", 8000))

    app.logger.setLevel("INFO")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )