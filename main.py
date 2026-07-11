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