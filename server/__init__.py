"""ASGI entry: uvicorn server.app:app --app-dir project root.

Bind: --host 127.0.0.1 (default, local only) or --host 0.0.0.0 for LAN.
Use env KARAOK_HOST when launching uvicorn, e.g. --host $env:KARAOK_HOST.
Audio devices stay on this machine; remote /live is browser-only.
"""
