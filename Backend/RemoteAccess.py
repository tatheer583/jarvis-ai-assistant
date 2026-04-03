"""
Jarvis Remote Access Server
Provides a Flask-based web API and web UI for remote access to Jarvis.
Run this alongside Main.py or use the integrated launcher.
"""

import logging
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime
from functools import wraps
from pathlib import Path

from dotenv import dotenv_values
from flask import Flask, jsonify, render_template_string, request, session

log = logging.getLogger("Jarvis.Remote")

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "Data"
TEMP_DIR = BASE_DIR / "Frontend" / "Files"

env_vars = dotenv_values(str(ENV_PATH))
AssistantName = env_vars.get("AssistantName", "Jarvis")
Username = env_vars.get("Username", "User")
REMOTE_PASSWORD = env_vars.get("RemotePassword", "")


def _read_remote_port() -> int:
    raw_port = env_vars.get("RemotePort")
    if raw_port is None or not str(raw_port).strip():
        return 5000
    try:
        return int(str(raw_port).strip())
    except ValueError:
        log.warning("Invalid RemotePort value %r in .env. Falling back to 5000.", raw_port)
        return 5000


REMOTE_PORT = _read_remote_port()
REMOTE_HOST = (env_vars.get("RemoteHost") or "127.0.0.1").strip()

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per-IP)
# ---------------------------------------------------------------------------
MAX_CHAT_PER_MINUTE = 30
MAX_LOGIN_PER_MINUTE = 5
MAX_QUERY_LENGTH = 2000
_rate_log: dict[str, list[float]] = defaultdict(list)
_login_rate_log: dict[str, list[float]] = defaultdict(list)
_rate_log_last_cleanup = time.time()
RATE_LOG_CLEANUP_INTERVAL = 300  # seconds


def _prune_rate_logs() -> None:
    global _rate_log_last_cleanup
    now = time.time()
    if now - _rate_log_last_cleanup < RATE_LOG_CLEANUP_INTERVAL:
        return
    _rate_log_last_cleanup = now
    stale = [ip for ip, ts in _rate_log.items() if not ts or now - ts[-1] > 120]
    for ip in stale:
        _rate_log.pop(ip, None)
    stale = [ip for ip, ts in _login_rate_log.items() if not ts or now - ts[-1] > 120]
    for ip in stale:
        _login_rate_log.pop(ip, None)


def _is_rate_limited() -> bool:
    _prune_rate_logs()
    ip = request.remote_addr or "unknown"
    now = time.time()
    timestamps = _rate_log[ip]
    timestamps[:] = [t for t in timestamps if now - t < 60]
    if len(timestamps) >= MAX_CHAT_PER_MINUTE:
        return True
    timestamps.append(now)
    return False


def _is_login_rate_limited() -> bool:
    ip = request.remote_addr or "unknown"
    now = time.time()
    timestamps = _login_rate_log[ip]
    timestamps[:] = [t for t in timestamps if now - t < 60]
    if len(timestamps) >= MAX_LOGIN_PER_MINUTE:
        return True
    timestamps.append(now)
    return False

# ---------------------------------------------------------------------------
# Lazy imports to avoid circular dependency at module load time
# ---------------------------------------------------------------------------
_chatbot_mod = None
_search_mod = None
_model_mod = None


def _get_chatbot():
    global _chatbot_mod
    if _chatbot_mod is None:
        from Backend.Chatbot import ChatBot
        _chatbot_mod = ChatBot
    return _chatbot_mod


def _get_search():
    global _search_mod
    if _search_mod is None:
        from Backend.RealtimeSearchEngine import RealtimeSearchEngine
        _search_mod = RealtimeSearchEngine
    return _search_mod


def _get_dmm():
    global _model_mod
    if _model_mod is None:
        from Backend.Model import FirstlayerDMM
        _model_mod = FirstlayerDMM
    return _model_mod


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _check_password(password: str) -> bool:
    if not REMOTE_PASSWORD:
        return True
    return password == REMOTE_PASSWORD


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not REMOTE_PASSWORD:
            return f(*args, **kwargs)
        if session.get("authenticated"):
            return f(*args, **kwargs)
        auth_header = request.headers.get("X-Auth-Token", "")
        if auth_header and _check_password(auth_header):
            return f(*args, **kwargs)
        return jsonify({"error": "Authentication required"}), 401
    return decorated


# ---------------------------------------------------------------------------
# Web UI Template
# ---------------------------------------------------------------------------
WEB_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ name }} - Remote Access</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            padding: 16px 24px;
            border-bottom: 1px solid #333;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header h1 {
            font-size: 22px;
            color: #00d4ff;
            font-weight: 600;
        }
        .header .status {
            font-size: 13px;
            color: #888;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .header .status .dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            background: #00ff88;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 20px 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .message {
            max-width: 75%;
            padding: 12px 16px;
            border-radius: 16px;
            font-size: 14px;
            line-height: 1.5;
            word-wrap: break-word;
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message.user {
            background: #1a3a5c;
            color: #fff;
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }
        .message.assistant {
            background: #1e1e2e;
            color: #d4d4d4;
            align-self: flex-start;
            border-bottom-left-radius: 4px;
            border: 1px solid #2a2a3a;
        }
        .message .role {
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .message.user .role { color: #00d4ff; }
        .message.assistant .role { color: #ff6b9d; }
        .message .time {
            font-size: 10px;
            color: #666;
            margin-top: 6px;
            text-align: right;
        }
        .input-area {
            padding: 16px 24px;
            background: #111;
            border-top: 1px solid #333;
            display: flex;
            gap: 12px;
        }
        .input-area input {
            flex: 1;
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 12px 16px;
            color: #fff;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }
        .input-area input:focus { border-color: #00d4ff; }
        .input-area input::placeholder { color: #555; }
        .input-area button {
            background: linear-gradient(135deg, #00d4ff, #0099cc);
            color: #000;
            border: none;
            border-radius: 12px;
            padding: 12px 24px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: transform 0.1s, opacity 0.2s;
        }
        .input-area button:hover { opacity: 0.9; }
        .input-area button:active { transform: scale(0.97); }
        .input-area button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .typing-indicator {
            display: none;
            align-self: flex-start;
            padding: 12px 16px;
            background: #1e1e2e;
            border-radius: 16px;
            border: 1px solid #2a2a3a;
        }
        .typing-indicator span {
            display: inline-block;
            width: 8px; height: 8px;
            border-radius: 50%;
            background: #555;
            margin: 0 2px;
            animation: typing 1.2s infinite;
        }
        .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
        .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes typing {
            0%, 100% { opacity: 0.3; transform: translateY(0); }
            50% { opacity: 1; transform: translateY(-4px); }
        }
        /* Login overlay */
        .login-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.95);
            display: flex; align-items: center; justify-content: center;
            z-index: 1000;
        }
        .login-box {
            background: #1a1a2e;
            padding: 40px;
            border-radius: 16px;
            text-align: center;
            border: 1px solid #333;
            max-width: 400px;
            width: 90%;
        }
        .login-box h2 { color: #00d4ff; margin-bottom: 20px; }
        .login-box input {
            width: 100%;
            background: #111;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px;
            color: #fff;
            font-size: 14px;
            margin-bottom: 16px;
            outline: none;
        }
        .login-box button {
            width: 100%;
            background: #00d4ff;
            color: #000;
            border: none;
            border-radius: 8px;
            padding: 12px;
            font-weight: 600;
            cursor: pointer;
        }
        .login-error { color: #ff4444; font-size: 13px; margin-top: 8px; }
        .hidden { display: none !important; }
    </style>
</head>
<body>
    {% if needs_auth %}
    <div class="login-overlay" id="loginOverlay">
        <div class="login-box">
            <h2>{{ name }} Remote Access</h2>
            <p style="color:#888; margin-bottom:20px;">Enter your password to continue</p>
            <input type="password" id="loginPassword" placeholder="Password" onkeypress="if(event.key==='Enter')doLogin()">
            <button onclick="doLogin()">Connect</button>
            <p class="login-error hidden" id="loginError">Invalid password</p>
        </div>
    </div>
    {% endif %}

    <div class="header">
        <h1>{{ name }} AI</h1>
        <div class="status">
            <div class="dot"></div>
            <span>Remote Session Active</span>
        </div>
    </div>

    <div class="chat-container" id="chatContainer">
        <div class="message assistant">
            <div class="role">{{ name }}</div>
            <div>Hello {{ user }}! I am {{ name }}, your AI assistant. You are connected remotely. How can I help you?</div>
            <div class="time">{{ time }}</div>
        </div>
    </div>

    <div class="typing-indicator" id="typingIndicator">
        <span></span><span></span><span></span>
    </div>

    <div class="input-area">
        <input type="text" id="messageInput" placeholder="Type your message..." onkeypress="if(event.key==='Enter')sendMessage()">
        <button id="sendBtn" onclick="sendMessage()">Send</button>
    </div>

    <script>
        let authToken = '';
        const needsAuth = {{ 'true' if needs_auth else 'false' }};

        function doLogin() {
            const pw = document.getElementById('loginPassword').value;
            fetch('/api/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: pw})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    authToken = pw;
                    document.getElementById('loginOverlay').classList.add('hidden');
                } else {
                    document.getElementById('loginError').classList.remove('hidden');
                }
            });
        }

        function addMessage(role, text) {
            const container = document.getElementById('chatContainer');
            const div = document.createElement('div');
            div.className = 'message ' + (role === 'user' ? 'user' : 'assistant');
            const now = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
            div.innerHTML = `<div class="role">${role === 'user' ? '{{ user }}' : '{{ name }}'}</div><div>${text}</div><div class="time">${now}</div>`;
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }

        function sendMessage() {
            const input = document.getElementById('messageInput');
            const text = input.value.trim();
            if (!text) return;

            addMessage('user', text);
            input.value = '';

            const btn = document.getElementById('sendBtn');
            btn.disabled = true;
            document.getElementById('typingIndicator').style.display = 'block';

            const headers = {'Content-Type': 'application/json'};
            if (authToken) headers['X-Auth-Token'] = authToken;

            fetch('/api/chat', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({query: text})
            })
            .then(r => r.json())
            .then(data => {
                document.getElementById('typingIndicator').style.display = 'none';
                btn.disabled = false;
                if (data.error) {
                    addMessage('assistant', 'Error: ' + data.error);
                } else {
                    addMessage('assistant', data.response);
                }
            })
            .catch(err => {
                document.getElementById('typingIndicator').style.display = 'none';
                btn.disabled = false;
                addMessage('assistant', 'Connection error: ' + err.message);
            });
        }

        if (!needsAuth) document.getElementById('messageInput').focus();
    </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(
        WEB_UI,
        name=AssistantName,
        user=Username,
        time=datetime.now().strftime("%I:%M %p"),
        needs_auth=bool(REMOTE_PASSWORD),
    )


@app.route("/api/login", methods=["POST"])
def api_login():
    if _is_login_rate_limited():
        return jsonify({"success": False, "error": "Too many attempts. Try again later."}), 429

    data = request.get_json(force=True)
    password = data.get("password", "")
    if _check_password(password):
        session["authenticated"] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid password"})


@app.route("/api/chat", methods=["POST"])
@require_auth
def api_chat():
    if _is_rate_limited():
        return jsonify({"error": "Rate limit exceeded. Try again shortly."}), 429

    data = request.get_json(force=True)
    query = str(data.get("query", "")).strip()
    if not query:
        return jsonify({"error": "Empty query"}), 400
    if len(query) > MAX_QUERY_LENGTH:
        return jsonify({"error": f"Query too long (max {MAX_QUERY_LENGTH} chars)."}), 400

    try:
        dmm = _get_dmm()
        decision = dmm(query)
        log.info("Remote query: %s -> Decision: %s", query, decision)

        realtime_detected = any(item.startswith("realtime") for item in decision)

        if realtime_detected:
            search_fn = _get_search()
            answer = search_fn(query)
        else:
            chatbot = _get_chatbot()
            answer = chatbot(query)

        return jsonify({
            "response": answer,
            "decision": decision,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        log.error("Remote chat error: %s", e)
        return jsonify({"error": "An internal error occurred. Please try again."}), 500


@app.route("/api/status", methods=["GET"])
@require_auth
def api_status():
    status = "Unknown"
    try:
        status_file = TEMP_DIR / "Status.data"
        if status_file.exists():
            status = status_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return jsonify({
        "assistant": AssistantName,
        "status": status,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok", "assistant": AssistantName})


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------
def start_remote_server(host: str | None = None, port: int | None = None, debug: bool = False):
    actual_host = host or REMOTE_HOST
    actual_port = port or REMOTE_PORT
    log.info("Starting %s Remote Access on http://%s:%d", AssistantName, actual_host, actual_port)
    if actual_host != "127.0.0.1":
        log.warning("Remote access is exposed on %s -- ensure you trust this network", actual_host)
    if REMOTE_PASSWORD:
        log.info("Remote access is password-protected")
    else:
        log.warning("Remote access has NO password. Set RemotePassword in .env for security.")
    app.run(host=actual_host, port=actual_port, debug=debug, use_reloader=False, threaded=True)


def start_remote_server_thread(host: str | None = None, port: int | None = None):
    thread = threading.Thread(
        target=start_remote_server,
        args=(host, port),
        daemon=True,
        name="RemoteAccessServer",
    )
    thread.start()
    return thread


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    start_remote_server(host="127.0.0.1", debug=True)