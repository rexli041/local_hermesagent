#!/usr/bin/env python3
"""
ACP Bridge: HTTP server that bridges Moodle to Hermes Agent via ACP stdio JSON-RPC.

Runs as www-data using the portable Python venv in moodledata/.hermes/.
Configuration read from Moodle config_plugins table via pymysql.
"""

import os
import sys
import json
import time
import uuid
import signal
import asyncio
import subprocess
from typing import Dict, Optional

HERMES_HOME = os.environ.get("HERMES_HOME", "/var/www/moodledata/.hermes")
PORT = int(os.environ.get("BRIDGE_PORT", "9118"))
MOODLE_DB_HOST = os.environ.get("MOODLE_DB_HOST", "mariadb")
MOODLE_DB_NAME = os.environ.get("MOODLE_DB_NAME", "moodle")
MOODLE_DB_USER = os.environ.get("MOODLE_DB_USER", "moodleuser")
MOODLE_DB_PASS = os.environ.get("MOODLE_DB_PASS", "")

import pymysql
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

app = FastAPI(title="Hermes ACP Bridge")

# Session registry: sid -> ACP process
sessions: Dict[str, subprocess.Popen] = {}


def get_db_config():
    """Read Moodle config for API key and provider settings."""
    try:
        conn = pymysql.connect(
            host=MOODLE_DB_HOST,
            database=MOODLE_DB_NAME,
            user=MOODLE_DB_USER,
            password=MOODLE_DB_PASS,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, value FROM mdl_config_plugins WHERE plugin=%s",
                ("local_hermesagent",)
            )
            rows = cur.fetchall()
        conn.close()
        return {row["name"]: row["value"] for row in rows}
    except Exception as e:
        print(f"DB config error: {e}", file=sys.stderr)
        return {}


def spawn_acp_session():
    """Spawn a new hermes acp subprocess."""
    hermes_bin = os.path.join(HERMES_HOME, "venv", "bin", "hermes")
    if not os.path.exists(hermes_bin):
        raise RuntimeError(f"Hermes not found at {hermes_bin}. Run bootstrap first.")
    
    env = os.environ.copy()
    env["HERMES_HOME"] = HERMES_HOME
    env["PATH"] = f"{HERMES_HOME}/venv/bin:{env.get('PATH', '/usr/bin:/bin')}"
    
    # Read config from DB
    config = get_db_config()
    if config.get("hermes_model"):
        env["HERMES_MODEL"] = config["hermes_model"]
    
    proc = subprocess.Popen(
        [hermes_bin, "acp", "--accept-hooks"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1
    )
    
    # Wait for it to be ready (first JSON line)
    try:
        first_line = proc.stdout.readline()
        if first_line:
            print(f"ACP started: {first_line.strip()}")
    except Exception:
        pass
    
    return proc


@app.get("/health")
def health():
    return {
        "status": "ok",
        "hermes_home": HERMES_HOME,
        "sessions": len(sessions),
        "hermes_bin": os.path.exists(os.path.join(HERMES_HOME, "venv", "bin", "hermes"))
    }


@app.post("/session/create")
def create_session():
    """Create a new ACP session."""
    try:
        proc = spawn_acp_session()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    sid = str(uuid.uuid4())[:8]
    sessions[sid] = proc
    return {"sid": sid, "status": "created"}


@app.post("/session/{sid}/send")
async def send_message(sid: str, request: dict):
    """Send a message to an ACP session and stream the response."""
    if sid not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    proc = sessions[sid]
    if proc.poll() is not None:
        del sessions[sid]
        raise HTTPException(status_code=410, detail="Session ended")
    
    message = json.dumps({
        "jsonrpc": "2.0",
        "method": "chat/send",
        "params": {"message": request.get("message", "")}
    }) + "\n"
    
    proc.stdin.write(message)
    proc.stdin.flush()
    
    async def stream_response():
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                data = line.strip()
                if not data:
                    continue
                try:
                    parsed = json.loads(data)
                    yield f"data: {json.dumps({'type': 'message', 'data': parsed})}\n\n"
                except json.JSONDecodeError:
                    yield f"data: {json.dumps({'type': 'raw', 'data': data})}\n\n"
                await asyncio.sleep(0)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
    
    return StreamingResponse(stream_response(), media_type="text/event-stream")


@app.post("/session/{sid}/tool_call")
def tool_call(sid: str, request: dict):
    """Call a tool on an ACP session."""
    if sid not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    proc = sessions[sid]
    if proc.poll() is not None:
        del sessions[sid]
        raise HTTPException(status_code=410, detail="Session ended")
    
    tool_call = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": request.get("name", ""),
            "arguments": request.get("arguments", {})
        }
    }
    
    proc.stdin.write(json.dumps(tool_call) + "\n")
    proc.stdin.flush()
    
    # Read response
    line = proc.stdout.readline()
    if line:
        try:
            return JSONResponse(content=json.loads(line.strip()))
        except json.JSONDecodeError:
            return JSONResponse(content={"raw": line.strip()})
    
    raise HTTPException(status_code=504, detail="No response from ACP")


@app.delete("/session/{sid}")
def delete_session(sid: str):
    """Kill an ACP session."""
    if sid not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    proc = sessions[sid]
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    del sessions[sid]
    return {"status": "terminated"}


@app.get("/session/{sid}/info")
def session_info(sid: str):
    """Get session info."""
    if sid not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    proc = sessions[sid]
    return {
        "sid": sid,
        "pid": proc.pid,
        "alive": proc.poll() is None
    }


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print("Shutting down ACP bridge...")
    for sid, proc in sessions.items():
        proc.terminate()
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def main():
    print(f"ACP Bridge v0.1")
    print(f"HERMES_HOME={HERMES_HOME}")
    print(f"Port={PORT}")
    print(f"DB Host={MOODLE_DB_HOST}")
    
    # Verify Hermes is available
    hermes_bin = os.path.join(HERMES_HOME, "venv", "bin", "hermes")
    if not os.path.exists(hermes_bin):
        print(f"ERROR: Hermes not found at {hermes_bin}")
        print("Run: scripts/bootstrap.sh")
        sys.exit(1)
    
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
