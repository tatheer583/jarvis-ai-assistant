"""The cloud-era remote HTTP server has been removed from Jarvis Local."""

def start_remote_server_thread(*args, **kwargs):
    raise RuntimeError("Remote HTTP access was removed. Launch Main.py to use the local desktop app.")
