#!/usr/bin/env python3
"""Tool-aware HTTP proxy for Hermes ACP chat."""
import asyncio, json, aiohttp, logging, os, subprocess, sys, time, re

UPSTREAM = "https://socratic.cs.cityu.edu.hk/ai-test"
PORT = 9118
API_KEY="1d90785d9594f5001583f921c1878fb57d711b94ab774d3f8136631c6c253706"
HERMES_HOME = os.environ.get("HERMES_HOME", "/var/www/moodledata/.hermes")
MCP_SCRIPT = os.path.join(HERMES_HOME, "mcp_servers", "moodle_db_mcp.py")
MCP_PYTHON = os.path.join(HERMES_HOME, "venv", "bin", "python")
LOG_FILE = os.path.join(HERMES_HOME, "logs", "proxy.log")

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("proxy")

# Tool definitions for the LLM
TOOLS = [
    {"type": "function", "function": {"name": "mcp_moodle_db_query",
        "description": "Run a safe read-only SQL query against the Moodle database.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "mcp_moodle_db_list_tables",
        "description": "List all Moodle database tables with row counts",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "mcp_moodle_db_describe_table",
        "description": "Show the structure of a specific table",
        "parameters": {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]}}},
    {"type": "function", "function": {"name": "mcp_moodle_db_schema_hints",
        "description": "Show key table descriptions to help construct queries",
        "parameters": {"type": "object", "properties": {}, "required": []}}}
]

# MCP tool execution
async def exec_mcp_tool(tool_name, arguments):
    """Execute an MCP tool and return the result."""
    mcp_name = tool_name
    if mcp_name.startswith("mcp_moodle_db_"):
        mcp_name = mcp_name[len("mcp_moodle_db_"):]
    init_msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "hermes-proxy", "version": "1.0"}}}
    call_msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": mcp_name, "arguments": arguments}}
    input_data = "\n".join([json.dumps(init_msg),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps(call_msg)]) + "\n"
    try:
        proc = await asyncio.create_subprocess_exec(
            MCP_PYTHON, MCP_SCRIPT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=1048576)
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=input_data.encode()), timeout=60)
        for line in stdout.decode().strip().split("\n"):
            if not line.strip(): continue
            try:
                data = json.loads(line)
                if data.get("id") == 2:
                    result = data.get("result", {})
                    for c in result.get("content", []):
                        if c.get("type") == "text":
                            try:
                                return json.loads(c["text"])
                            except:
                                return {"result": c["text"]}
                    if "error" in result:
                        return {"error": str(result["error"])}
            except json.JSONDecodeError:
                continue
        return {"error": "No result"}
    except Exception as e:
        log.error("MCP tool error: %s %s", tool_name, e)
        return {"error": str(e)}

def parse_tool_call(text):
    """Parse tool calls like call:prefix:name{json} from text.
    Must match the specific pattern: call:[prefix]:[name]{JSON}
    where name is non-empty and JSON contains recognized keys."""
    results = []
    for m in re.finditer(r"call:[\w_]+:([\w_]+)\s*(\{[^}]*(?:\{[^}]*\}[^}]*)*\})", text):
        name = m.group(1).strip()
        if not name:
            continue
        if len(name) < 2:  # Skip very short names (likely false matches)
            continue
        try:
            args = json.loads(m.group(2))
            # Verify it looks like a real tool call (has at least one key)
            if not isinstance(args, dict) or len(args) == 0:
                continue
            results.append({"name": name, "arguments": args})
        except:
            pass
    return results


async def handle(reader, writer):
    try:
        req_line = await asyncio.wait_for(reader.readline(), 300)
        if not req_line:
            writer.close(); return
        parts = req_line.decode().strip().split()
        if len(parts) < 2:
            writer.close(); return
        method, http_path = parts[0], parts[1]
        
        if http_path == "/health":
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\"}")
            await writer.drain(); writer.close(); return
        
        headers = {}; cl = 0
        while True:
            ln = await asyncio.wait_for(reader.readline(), 300)
            if ln in (b"\r\n", b"\n", b""):
                break
            if ":" not in ln.decode():
                break
            k, v = ln.decode().strip().split(":", 1)
            headers[k.strip().lower()] = v.strip()
            if k.strip().lower() == "content-length":
                cl = int(v.strip())
        
        body = b""
        if cl > 0:
            body = await asyncio.wait_for(reader.read(cl), 300)
        
        body_dict = json.loads(body) if body else {}
        body_dict.setdefault("stream", True)
        body_dict.setdefault("tools", TOOLS)
        body_dict.setdefault("tool_choice", "auto")
        
        log.info("Request: %d msgs, tools=auto", len(body_dict.get("messages", [])))
        
        upstream = UPSTREAM + http_path
        async with aiohttp.ClientSession() as sess:
            uh = {"Content-Type": "application/json"}
            uh["Authorization"] = headers.get("authorization") or ("Bearer " + API_KEY)
            async with sess.post(upstream, json=body_dict, headers=uh,
                    timeout=aiohttp.ClientTimeout(total=300)) as resp:
                writer.write(b"HTTP/1.1 " + str(resp.status).encode() + b" OK\r\n")
                writer.write(b"Content-Type: text/event-stream\r\n")
                writer.write(b"Cache-Control: no-cache\r\n")
                writer.write(b"Connection: keep-alive\r\n\r\n")
                await writer.drain()
                
                session_id = None
                while True:
                    chunk = await asyncio.wait_for(resp.content.readline(), 300)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace").strip()
                    
                    if text.startswith("data: "):
                        payload = text[6:]
                        if payload == "[DONE]":
                            writer.write(b"data: {\"done\":true}\n\n")
                            await writer.drain()
                            break
                        
                        try:
                            data = json.loads(payload)
                            if "id" in data and not session_id:
                                session_id = data["id"]
                            
                            for choice in data.get("choices", []):
                                delta = choice.get("delta", {})
                                content = delta.get("content", "")
                                reasoning = delta.get("reasoning", "")
                                
                                # Handle tool calls from delta
                                for tc in delta.get("tool_calls", []):
                                    tc_name = tc.get("function", {}).get("name", "")
                                    if not tc_name:
                                        continue  # Skip empty tool names
                                    try:
                                        tc_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                                    except:
                                        tc_args = {}
                                    if not tc_args:
                                        log.warning("Skipping tool call '%s' with empty args", tc_name)
                                        continue
                                    result = await exec_mcp_tool(tc_name, tc_args)
                                    # Skip invalid results
                                    if not result or (isinstance(result, dict) and result.get("error")):
                                        log.warning("Skipping invalid tool result: %s -> %s", tc_name, str(result))
                                        continue
                                    log.info("Tool result: %s -> %s", tc_name, str(result)[:200])
                                    # Send tool_call event
                                    tool_evt = {"tool_call": {"id": "call_1", "name": tc_name, "input": tc_args, "result": result, "status": "completed"}}
                                    evt_str = "data: " + json.dumps(tool_evt) + "\n\n"
                                    writer.write(evt_str.encode())
                                    await writer.drain()
                                    # Send result as content
                                    rt = json.dumps(result, ensure_ascii=False)
                                    result_delta = {"delta": "\n[Result: " + rt + "]\n\n"}
                                    if session_id:
                                        result_delta["session_id"] = session_id
                                    rd_str = "data: " + json.dumps(result_delta) + "\n\n"
                                    writer.write(rd_str.encode())
                                    await writer.drain()
                                
                                # Also check text content for tool calls (legacy format)
                                for tc in parse_tool_call(content):
                                    result = await exec_mcp_tool(tc["name"], tc["arguments"])
                                    # Skip invalid results
                                    if not result or isinstance(result, dict) and result.get("error"):
                                        log.warning("Skipping invalid tool result: %s -> %s", tc["name"], str(result))
                                        continue
                                    log.info("Tool result (text): %s -> %s", tc["name"], str(result)[:200])
                                    tool_evt = {"tool_call": {"id": "call_1", "name": tc["name"], "input": tc["arguments"], "result": result, "status": "completed"}}
                                    evt_str = "data: " + json.dumps(tool_evt) + "\n\n"
                                    writer.write(evt_str.encode())
                                    await writer.drain()
                                    rt = json.dumps(result, ensure_ascii=False)
                                    result_delta = {"delta": "\n[Result: " + rt + "]\n\n"}
                                    if session_id:
                                        result_delta["session_id"] = session_id
                                    rd_str = "data: " + json.dumps(result_delta) + "\n\n"
                                    writer.write(rd_str.encode())
                                    await writer.drain()
                                
                                if content or reasoning:
                                    transformed = {"delta": content}
                                    if reasoning:
                                        transformed["reasoning"] = reasoning
                                    if session_id:
                                        transformed["session_id"] = session_id
                                    msg_str = "data: " + json.dumps(transformed) + "\n\n"
                                    writer.write(msg_str.encode())
                                    await writer.drain()
                        
                        except json.JSONDecodeError:
                            writer.write(chunk)
                    else:
                        writer.write(chunk)
                    await writer.drain()
        
        writer.close()
    
    except Exception as e:
        log.error("Handler error: %s", e, exc_info=True)
        try:
            writer.write(("HTTP/1.1 500\r\n\r\n" + str(e)).encode())
            await writer.drain()
            writer.close()
        except:
            pass

async def main():
    srv = await asyncio.start_server(handle, "127.0.0.1", PORT)
    log.info("Proxy on 127.0.0.1:%d -> %s (tool-aware)", PORT, UPSTREAM)
    print("Proxy on 127.0.0.1:%d -> %s (tool-aware)" % (PORT, UPSTREAM), flush=True)
    async with srv:
        await srv.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
