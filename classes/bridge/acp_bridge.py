#!/usr/bin/env python3
import os
import json
import uuid
import asyncio
import subprocess
import sys
from typing import Dict
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
import uvicorn

HERMES_HOME = os.environ.get("HERMES_HOME", "/var/www/moodledata/.hermes")
PORT = int(os.environ.get("BRIDGE_PORT", "9118"))
env_path = os.path.join(HERMES_HOME, ".env")
env_loaded = load_dotenv(dotenv_path=env_path, override=True)

app = FastAPI(title="Hermes ACP Bridge")
sessions: Dict[str, 'ACPSession'] = {}

class ACPSession:
    def __init__(self, sid: str):
        self.sid = sid
        self.acp_session_id = None
        self.req_id = 0
        
        cmd = [f"{HERMES_HOME}/venv/bin/hermes", "acp", "--accept-hooks"]

        bridge_env = os.environ.copy()

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
            cwd=HERMES_HOME,
            env=bridge_env
        )

    async def send_rpc(self, method: str, params: dict):
        """发送 JSON-RPC 请求给 Hermes 底层进程"""
        self.req_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": method,
            "params": params
        }
        msg = json.dumps(req) + "\n"
        self.proc.stdin.write(msg)
        self.proc.stdin.flush()

    async def read_response(self) -> dict:
        """非阻塞地读取 Hermes 底层进程的返回结果"""
        line = await asyncio.to_thread(self.proc.stdout.readline)
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            print(f"[WARN] 无法解析的输出: {line}", flush=True)
            return {"error": {"message": "JSON Decode Error"}}

# ---------------- API 路由映射 ----------------

@app.get("/health")
def health_check():
    """供 Moodle api.php 调用的健康检查接口，解决 Bridge 永远显示 stopped 的问题"""
    return {"status": "ok", "message": "ACP Bridge is running", "sessions_active": len(sessions)}

@app.get("/status")
def status_check():
    return {"status": "running"}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """兼容 OpenAI 格式的入口，接住 api.php 转发过来的聊天请求"""
    data = await request.json()
    
    # 解析前端传来的数据
    messages = data.get("messages", [])
    session_id = data.get("session_id", str(uuid.uuid4())[:8])
    
    # 提取用户发送的最新一条消息
    user_msg = ""
    if messages and len(messages) > 0:
        user_msg = messages[-1].get("content", "")
    
    # 如果会话不存在，则初始化底层 ACP 握手协议
    if session_id not in sessions:
        s = ACPSession(session_id)
        sessions[session_id] = s
        
        # 1. 握手
        await s.send_rpc("initialize", {"protocolVersion": "1.0", "capabilities": {}})
        await s.read_response()
        
        # 2. 创建底层 Session
        await s.send_rpc("session/new", {"cwd": HERMES_HOME, "mcpServers": []})
        resp = await s.read_response()
        
        if resp and "result" in resp and isinstance(resp["result"], dict):
            # 获取真正的 agent session id
            s.acp_session_id = resp["result"].get("sessionId", session_id)
        else:
            s.acp_session_id = session_id
    else:
        s = sessions[session_id]

    # 构建并发送 Prompt 任务给模型
    prompt_payload = [{"type": "text", "text": user_msg}]
    await s.send_rpc("session/prompt", {
        "sessionId": s.acp_session_id,
        "prompt": prompt_payload
    })
    
    # 流式读取与解析逻辑
    async def stream_generator():
        while True:
            r = await s.read_response()
            if not r: 
                break
            
            # 如果底层报错，转发给前端
            if "error" in r:
                err_msg = r["error"].get("message", "Unknown error")
                yield f"data: {json.dumps({'error': err_msg})}\n\n"
                break
            
            # 解析标准 ACP 流式更新
            params = r.get("params", {})
            update = params.get("update", {})
            session_update = update.get("sessionUpdate", "")

            # 精准抓取 AI 回复的文本片段
            if session_update == "agent_message_chunk":
                delta_text = update.get("content", {}).get("text", "")
                if delta_text:
                    # 返回 Moodle 前端期待的简单 JSON 格式
                    yield f"data: {json.dumps({'delta': delta_text})}\n\n"
            
            # 判断回合是否结束
            if "result" in r and isinstance(r["result"], dict):
                if r["result"].get("stopReason") == "end_turn":
                    # 发送结束标记
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    break
                    
    return StreamingResponse(stream_generator(), media_type="text/event-stream")

# ---------------- 启动入口 ----------------
if __name__ == "__main__":
    print(f"启动 Hermes ACP Bridge，监听端口 {PORT}...")
    uvicorn.run(app, host="127.0.0.1", port=PORT)