from flask import Flask, request, jsonify
import json

app = Flask(__name__)

# In-memory storage for demo
sessions = {}  # token -> session_id
game_sessions = {}  # game_id -> {config, users, etc.}
users = {}  # user_id -> info

@app.route('/user', methods=['POST'])
def create_user():
    data = request.get_json(silent=True) or {}
    # Expect fields: platform, auth_token, version, client_version
    # For simplicity, generate dummy session and token
    session_id = "dummy_session_id"
    mgi_token = "dummy_mgi_token"
    sessions[mgi_token] = session_id
    return jsonify({"session_id": session_id, "mgi_token": mgi_token})

@app.route('/auth', methods=['GET'])
def auth():
    # The client sends MGI-Bearer-Token header
    token = request.headers.get('MGI-Bearer-Token')
    # Just validate that token exists in our sessions (optional)
    return jsonify({}), 200

@app.route('/game', methods=['GET'])
def browse():
    # Query params: start_idx, max_results, category, val (multiple)
    # Return BrowseResponse with empty games list
    return jsonify({"games": []})

@app.route('/game/<game_id>', methods=['GET'])
def game_info(game_id):
    # Similar to browse but for a specific game
    # Return a single game object inside games list? Actually BrowseResponse expects list.
    # We'll return a list with one dummy game or empty.
    # For simplicity, return empty list.
    return jsonify({"games": []})

@app.route('/game/<game_id>/round/<round_id>', methods=['GET'])
def round_info(game_id, round_id):
    return jsonify({"games": []})  # same as above

@app.route('/game/<game_id>/reservation', methods=['POST'])
def reserve_slots(game_id):
    # Expect JSON with count
    return jsonify({}), 200

@app.route('/game', methods=['POST'])
def create_game():
    data = request.get_json(silent=True) or {}
    # Expect backend, config, category, tid
    game_id = "game_" + str(len(game_sessions) + 1)
    game_sessions[game_id] = {
        "config": data.get("config", {}),
        "users": [],
    }
    return jsonify({"id": game_id})

@app.route('/game/<game_id>/add_user', methods=['POST'])
def add_user(game_id):
    data = request.get_json(silent=True) or {}
    # Expect reservation and trn_user_subgroup
    # Dummy user
    user_id = "user_" + str(len(users) + 1)
    users[user_id] = {"id": user_id}
    if game_id in game_sessions:
        game_sessions[game_id]["users"].append(user_id)
    return jsonify({}), 200

@app.route('/game/<game_id>', methods=['POST'])
def set_game_info(game_id):
    data = request.get_json(silent=True) or {}
    if game_id in game_sessions:
        game_sessions[game_id]["config"] = data.get("config", {})
    return jsonify({}), 200

@app.route('/game/<game_id>/op/<op>', methods=['POST'])
def game_op(game_id, op):
    # No data needed
    return jsonify({}), 200

@app.route('/game/<game_id>/del_user', methods=['POST'])
def remove_user(game_id):
    data = request.get_json(silent=True) or {}
    # Expect reason
    return jsonify({}), 200

@app.route('/game/<game_id>/del_user/<user_id>', methods=['POST'])
def kick_user(game_id, user_id):
    return jsonify({}), 200

@app.route('/game/<game_id>/round/<round_id>/participants', methods=['GET'])
def participants(game_id, round_id):
    # Return UserSessionInfoList
    return jsonify({"users": []})

@app.route('/game/<game_id>/users', methods=['GET'])
def users_in_game(game_id):
    return jsonify({"users": []})

@app.route('/user/<user_id>', methods=['GET'])
def get_user(user_id):
    # Return UserSessionInfo
    # Provide minimal fields
    return jsonify({
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
        "rollingPoints": 0
    })

@app.route('/user/config', methods=['POST'])
def set_user_info():
    data = request.get_json(silent=True) or {}
    return jsonify({}), 200

@app.route('/game/<game_id>/round/<round_id>/score', methods=['POST'])
def post_score_event(game_id, round_id):
    data = request.get_json(silent=True) or {}
    return jsonify({}), 200

@app.route('/invitation/consume', methods=['POST'])
def consume_invitation():
    data = request.get_json(silent=True) or {}
    return jsonify({}), 200

@app.route('/invitation/send', methods=['POST'])
def invite_bunch():
    data = request.get_json(silent=True) or {}
    return jsonify({}), 200

@app.route('/info/connection', methods=['POST'])
def report_connection():
    data = request.get_json(silent=True) or {}
    return jsonify({}), 200

@app.route('/newsfeed/list', methods=['GET'])
def newsfeed_list():
    return jsonify({"items": []})

@app.route('/newsfeed/<int:item_id>', methods=['GET'])
def newsfeed_item(item_id):
    return jsonify({})

@app.route('/analytics/postrace', methods=['POST'])
def post_race_analytics():
    data = request.get_json(silent=True) or {}
    return jsonify({}), 200

@app.route('/leaderboard/<lb_name>/<kind>', methods=['GET'])
def leaderboard_query(lb_name, kind):
    start_at = request.args.get('start_at', type=int, default=0)
    count = request.args.get('count', type=int, default=0)
    return jsonify({
        "entries": [],
        "total": 0
    })

@app.route('/leaderboard', methods=['POST'])
def leaderboard_post():
    data = request.get_json(silent=True) or {}
    return jsonify({
        "entries": [],
        "total": 0
    }), 200

@app.route('/leaderboard/advance_time', methods=['POST'])
def advance_leaderboard_time():
    data = request.get_json(silent=True) or {}
    return jsonify({
        "entries": [],
        "total": 0
    }), 200

@app.route('/stats', methods=['GET'])
def get_stats():
    category = request.args.get('category', '')
    return jsonify({
        "values": {}
    })

@app.route('/tournament/event_info/<adv>/<subgroup>', methods=['GET'])
def tournament_event_info(adv, subgroup):
    return jsonify({})

@app.route('/tournament/history/<adv>/<subgroup>', methods=['GET'])
def tournament_history(adv, subgroup):
    return jsonify({})

@app.route('/challenge/list', methods=['GET'])
def challenge_list():
    # Expect query params limit, published, full
    return jsonify({
        "challenges": []
    })

@app.route('/challenge/leaderboard/<assists_level>', methods=['GET'])
def challenge_leaderboard(assists_level):
    return jsonify({
        "entries": []
    })

@app.route('/challenge/completed/<challenge_id>', methods=['POST'])
def post_challenge_leaderboard(challenge_id):
    data = request.get_json(silent=True) or {}
    return jsonify({
        "entries": []
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)