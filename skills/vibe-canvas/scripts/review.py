#!/usr/bin/env python3
import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
import zlib

sys.dont_write_bytecode = True

PORT = int(os.environ.get("CANVAS_REVIEW_PORT", "7193"))
ENDPOINT = os.environ.get("CANVAS_REVIEW_URL", f"http://localhost:{PORT}")
APP_ORIGINS = ["https://app.vibe-beta.com"]
KINDS = {"take_snapshot", "get_viewport", "set_viewport", "get_zoom", "set_zoom"}
MAX_PAYLOAD = 32 * 1024 * 1024
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
REVIEW_MAX_ZOOM = 1.0
REVIEW_PADDING = 0.1
SNAPSHOT_MAX_SIDE = 1280


def is_local_host(host):
    return bool(re.fullmatch(r"(localhost|127\.0\.0\.1)(:\d+)?", host or ""))


def is_app_origin(origin):
    if re.fullmatch(r"https?://(localhost|127\.0\.0\.1)(:\d+)?", origin or ""):
        return True
    extra = [value.strip() for value in os.environ.get("CANVAS_REVIEW_ORIGINS", "").split(",") if value.strip()]
    return origin in APP_ORIGINS + extra


def validate(body):
    board_id = body.get("boardId")
    operation = body.get("operation")
    if not isinstance(board_id, str) or not board_id.strip():
        raise ValueError("boardId is required.")
    if not isinstance(operation, dict) or operation.get("kind") not in KINDS:
        raise ValueError("Unknown operation.")
    finite = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) != float("inf") and value == value
    if operation["kind"] == "set_zoom" and not (finite(operation.get("level")) and 10 <= operation["level"] <= 300):
        raise ValueError("Zoom must be between 10 and 300 percent.")
    if operation["kind"] == "set_viewport":
        edges = [operation.get(key) for key in ("left", "top", "right", "bottom")]
        if not all(finite(edge) for edge in edges) or edges[2] <= edges[0] or edges[3] <= edges[1]:
            raise ValueError("Viewport must have finite edges and a positive size.")
    timeout = body.get("timeout")
    if timeout is not None and not (finite(timeout) and 0 < timeout <= 12):
        raise ValueError("Timeout must be between 0 and 12 seconds.")
    collect = body.get("collect") is True
    return board_id, operation, timeout, collect


class Socket:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.open = True

    def send(self, text, opcode=0x1):
        payload = text.encode() if isinstance(text, str) else text
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, length)
        elif length < 1 << 16:
            header = struct.pack("!BBH", 0x80 | opcode, 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 127, length)
        self.writer.write(header + payload)

    async def receive(self):
        parts = []
        total = 0
        while True:
            first, second = await self.reader.readexactly(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", await self.reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", await self.reader.readexactly(8))[0]
            if not second & 0x80:
                raise ConnectionError("Client frames must be masked.")
            mask = await self.reader.readexactly(4)
            if opcode < 0x8:
                total += length
                if total > MAX_PAYLOAD:
                    raise ConnectionError("Message too large.")
            data = await self.reader.readexactly(length)
            key = (mask * (length // 4 + 1))[:length]
            data = (int.from_bytes(data, "little") ^ int.from_bytes(key, "little")).to_bytes(length, "little")
            if opcode == 0x8:
                return None
            if opcode == 0x9:
                self.send(data, 0xA)
                continue
            if opcode == 0xA:
                continue
            parts.append(data)
            if first & 0x80:
                return b"".join(parts)

    def close(self):
        self.open = False
        self.writer.close()


class ReviewServer:
    def __init__(self, timeout=12.0):
        self.timeout = timeout
        self.sockets = set()
        self.pending = {}

    async def handle(self, reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        method, path = (lines[0].split(" ") + ["", ""])[:2]
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        if headers.get("upgrade", "").lower() == "websocket":
            await self.upgrade(reader, writer, headers)
        else:
            await self.http(reader, writer, method, path, headers)

    async def http(self, reader, writer, method, path, headers):
        def send(status, body):
            data = json.dumps(body).encode()
            reason = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 415: "Unsupported Media Type"}[status]
            writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data)

        try:
            if not is_local_host(headers.get("host")):
                return send(403, {"ok": False, "error": "Forbidden host."})
            if method == "GET" and path == "/health":
                return send(200, {"ok": True, "connections": len(self.sockets)})
            if method != "POST" or path != "/operation":
                return send(404, {"ok": False, "error": "Not found"})
            if "origin" in headers:
                return send(403, {"ok": False, "error": "Browser requests are not allowed."})
            if not re.match(r"application/json(;|$)", headers.get("content-type", "")):
                return send(415, {"ok": False, "error": "Content-Type must be application/json."})
            try:
                length = int(headers.get("content-length", "0"))
                if length > 8192:
                    raise ValueError("Request too large.")
                board_id, operation, timeout, collect = validate(json.loads(await reader.readexactly(length)))
                send(200, await (self.count(board_id, operation, timeout) if collect else self.request(board_id, operation, timeout)))
            except (ValueError, TimeoutError, ConnectionError, asyncio.IncompleteReadError) as error:
                send(400, {"ok": False, "error": str(error)})
        finally:
            try:
                await writer.drain()
            finally:
                writer.close()

    async def upgrade(self, reader, writer, headers):
        key = headers.get("sec-websocket-key")
        if not key or not is_local_host(headers.get("host")) or not is_app_origin(headers.get("origin")):
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        writer.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode())
        socket = Socket(reader, writer)
        self.sockets.add(socket)
        try:
            while True:
                data = await socket.receive()
                if data is None:
                    break
                self.resolve(socket, data)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.sockets.discard(socket)
            socket.close()

    def resolve(self, socket, data):
        try:
            reply = json.loads(data)
        except ValueError:
            return
        if not isinstance(reply, dict):
            return
        request = self.pending.get(reply.get("id"))
        if not request or request["board_id"] != reply.get("boardId") or request["kind"] != reply.get("kind") or socket not in request["clients"]:
            return
        request["answered"].add(socket)
        if request.get("collect"):
            return
        del self.pending[reply["id"]]
        if not request["future"].done():
            request["future"].set_result(reply)

    async def request(self, board_id, operation, timeout=None):
        clients = {socket for socket in self.sockets if socket.open}
        if not clients:
            raise ConnectionError("No board tab connected. Open the board with web-agent-socket enabled.")
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = {"board_id": board_id, "kind": operation["kind"], "clients": clients, "future": future, "answered": set()}
        message = json.dumps({"id": request_id, "boardId": board_id, "operation": operation})
        for socket in clients:
            socket.send(message)
        try:
            reply = await asyncio.wait_for(future, timeout or self.timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Board {board_id} did not answer {operation['kind']}. Check the board ID and that its tab is open in front.")
        finally:
            self.pending.pop(request_id, None)
        if reply.get("ok") is not True:
            raise ValueError(reply.get("error") or "Board operation failed.")
        return reply


    async def count(self, board_id, operation, timeout=None):
        clients = {socket for socket in self.sockets if socket.open}
        request_id = str(uuid.uuid4())
        request = {"board_id": board_id, "kind": operation["kind"], "clients": clients, "future": None, "answered": set(), "collect": True}
        self.pending[request_id] = request
        message = json.dumps({"id": request_id, "boardId": board_id, "operation": operation})
        for socket in clients:
            socket.send(message)
        try:
            await asyncio.sleep(timeout or 1)
        finally:
            self.pending.pop(request_id, None)
        return {"ok": True, "boardId": board_id, "tabs": len(request["answered"])}


async def serve(port):
    review = ReviewServer()
    server = await asyncio.start_server(review.handle, "127.0.0.1", port, limit=1 << 16)
    print(f"Canvas review listening on http://localhost:{port}", flush=True)
    async with server:
        await server.serve_forever()


def call(path, body=None):
    request = urllib.request.Request(ENDPOINT + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            reply = json.loads(response.read())
    except urllib.error.HTTPError as error:
        reply = json.loads(error.read() or b"{}")
    except urllib.error.URLError:
        raise SystemExit(f"Review server is not running at {ENDPOINT}, or this sandbox blocks localhost. Start it with: python3 {sys.argv[0]} serve")
    if not reply.get("ok"):
        raise SystemExit(reply.get("error") or "Review request failed.")
    return reply


def operate(board_id, operation, timeout=None, collect=False):
    reply = call("/operation", {"boardId": board_id, "operation": operation, **({"timeout": timeout} if timeout else {}), **({"collect": True} if collect else {})})
    deadline = time.monotonic() + 2.5
    previous = None
    if operation["kind"] == "set_zoom":
        while time.monotonic() < deadline:
            level = call("/operation", {"boardId": board_id, "operation": {"kind": "get_zoom"}})["level"]
            if abs(level - operation["level"]) < 0.5 and level == previous:
                return {**reply, "level": level}
            previous = level
            time.sleep(0.05)
        raise SystemExit("The engine did not reach the requested zoom; inspect the current view before retrying.")
    if operation["kind"] == "set_viewport":
        want = operation
        while time.monotonic() < deadline:
            actual = call("/operation", {"boardId": board_id, "operation": {"kind": "get_viewport"}})
            view = actual.get("viewport")
            covers = view and view["left"] <= want["left"] + 1 and view["top"] <= want["top"] + 1 and view["right"] >= want["right"] - 1 and view["bottom"] >= want["bottom"] - 1
            fitted = covers and min((view["right"] - view["left"]) / (want["right"] - want["left"]), (view["bottom"] - view["top"]) / (want["bottom"] - want["top"])) <= 1.05
            if fitted and previous and all(abs(view[key] - previous[key]) < 0.1 for key in ("left", "top", "right", "bottom")):
                return {**reply, "viewport": view, "zoomScale": actual.get("zoomScale")}
            previous = view
            time.sleep(0.1)
        raise SystemExit("The engine viewport did not settle around the requested region.")
    return reply


def wait_ready(board, seconds):
    deadline = time.monotonic() + seconds
    while True:
        try:
            return operate(board, {"kind": "get_viewport"}, 1)
        except SystemExit as error:
            if "not running" in str(error) or time.monotonic() >= deadline:
                raise
        time.sleep(0.5)


def decode_png(data):
    position, chunks, header = 8, [], None
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            chunks.append(body)
    if not header or header[2] != 8 or header[3] not in (2, 6) or header[6]:
        return None
    width, height, bpp = header[0], header[1], 4 if header[3] == 6 else 3
    raw = zlib.decompress(b"".join(chunks))
    stride = width * bpp
    low, high = int.from_bytes(b"\x7f" * stride, "big"), int.from_bytes(b"\x80" * stride, "big")
    previous, rows = bytes(stride), []
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], raw[start + 1:start + 1 + stride]
        if kind == 2:
            a, b = int.from_bytes(line, "big"), int.from_bytes(previous, "big")
            line = (((a & low) + (b & low)) ^ ((a ^ b) & high)).to_bytes(stride, "big")
        elif kind:
            out = bytearray(line)
            for i in range(stride):
                left = out[i - bpp] if i >= bpp else 0
                up = previous[i]
                if kind == 1:
                    out[i] = (out[i] + left) & 255
                elif kind == 3:
                    out[i] = (out[i] + ((left + up) >> 1)) & 255
                else:
                    corner = previous[i - bpp] if i >= bpp else 0
                    guess = left + up - corner
                    pa, pb, pc = abs(guess - left), abs(guess - up), abs(guess - corner)
                    out[i] = (out[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
            line = bytes(out)
        rows.append(line)
        previous = line
    return width, height, bpp, header[3], rows


def average_bytes(a, b):
    size = len(a)
    x, y = int.from_bytes(a, "big"), int.from_bytes(b, "big")
    mask = int.from_bytes(b"\xfe" * size, "big")
    return ((x & y) + (((x ^ y) & mask) >> 1)).to_bytes(size, "big")


def halve(width, height, bpp, rows):
    width, height = width // 2, height // 2
    halved = []
    for y in range(height):
        row = average_bytes(rows[2 * y][:width * 2 * bpp], rows[2 * y + 1][:width * 2 * bpp])
        out = bytearray(width * bpp)
        for channel in range(bpp):
            out[channel::bpp] = average_bytes(row[channel::2 * bpp], row[bpp + channel::2 * bpp])
        halved.append(bytes(out))
    return width, height, halved


def encode_png(width, height, color, rows):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    pixels = zlib.compress(b"".join(b"\x00" + row for row in rows), 6)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def shrink_png(data, max_side, crop=None):
    decoded = decode_png(data) if max_side or crop else None
    if not decoded:
        return data
    width, height, bpp, color, rows = decoded
    if crop:
        left, top, right, bottom = crop
        rows = [row[left * bpp:right * bpp] for row in rows[top:bottom]]
        width, height = right - left, bottom - top
    elif max(width, height) <= max_side:
        return data
    while max_side and max(width, height) > max_side and min(width, height) > 1:
        width, height, rows = halve(width, height, bpp, rows)
    return encode_png(width, height, color, rows)


def crop_box(bounds, width, height, region):
    scale_x = width / (bounds["right"] - bounds["left"])
    scale_y = height / (bounds["bottom"] - bounds["top"])
    left = max(0, int((region[0] - bounds["left"]) * scale_x))
    top = max(0, int((region[1] - bounds["top"]) * scale_y))
    right = min(width, int((region[2] - bounds["left"]) * scale_x + 0.999))
    bottom = min(height, int((region[3] - bounds["top"]) * scale_y + 0.999))
    if right <= left or bottom <= top:
        raise SystemExit("The region is outside the current view. Pan there first.")
    world = {"left": bounds["left"] + left / scale_x, "top": bounds["top"] + top / scale_y, "right": bounds["left"] + right / scale_x, "bottom": bounds["top"] + bottom / scale_y}
    return (left, top, right, bottom), world


def png_size(data):
    return struct.unpack(">II", data[16:24])


def fit_region(board, left, top, right, bottom):
    current = operate(board, {"kind": "get_viewport"})
    view, zoom = current["viewport"], current["zoomScale"]
    window_w = (view["right"] - view["left"]) * zoom
    window_h = (view["bottom"] - view["top"]) * zoom
    width = max(right - left, 1) * (1 + 2 * REVIEW_PADDING)
    height = max(bottom - top, 1) * (1 + 2 * REVIEW_PADDING)
    aspect = window_w / window_h
    if width / height < aspect:
        width = height * aspect
    else:
        height = width / aspect
    if window_w / width > REVIEW_MAX_ZOOM:
        width, height = window_w / REVIEW_MAX_ZOOM, window_h / REVIEW_MAX_ZOOM
    cx, cy = (left + right) / 2, (top + bottom) / 2
    return {"left": cx - width / 2, "top": cy - height / 2, "right": cx + width / 2, "bottom": cy + height / 2}


def board_id(value):
    if "://" not in value:
        return value
    segments = [segment for segment in urllib.parse.urlparse(value).path.split("/") if segment]
    if not segments:
        raise SystemExit("Use a board URL or board ID.")
    return segments[0]


def main():
    parser = argparse.ArgumentParser(description="Visual review of an open Vibe Canvas board tab.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    commands.add_parser("health")
    commands.add_parser("open").add_argument("url")
    wait = commands.add_parser("wait")
    wait.add_argument("board")
    wait.add_argument("seconds", type=float, nargs="?", default=15)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("board")
    snapshot.add_argument("png")
    snapshot.add_argument("--max-side", type=int, default=SNAPSHOT_MAX_SIDE)
    snapshot.add_argument("--full", action="store_true")
    snapshot.add_argument("--region", type=float, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    commands.add_parser("viewport").add_argument("board")
    commands.add_parser("tabs").add_argument("board")
    pan = commands.add_parser("pan")
    pan.add_argument("board")
    for edge in ("left", "top", "right", "bottom"):
        pan.add_argument(edge, type=float)
    zoom = commands.add_parser("zoom")
    zoom.add_argument("board")
    zoom.add_argument("percent", type=float, nargs="?")
    args = parser.parse_args()

    if args.command == "serve":
        try:
            asyncio.run(serve(PORT))
        except KeyboardInterrupt:
            pass
        except OSError as error:
            raise SystemExit(f"Cannot listen on port {PORT}: {error.strerror or error}. If the review server is already running, reuse it; in a sandbox, run this script outside it.")
        return
    if args.command == "open":
        if urllib.parse.urlparse(args.url).scheme not in ("http", "https"):
            raise SystemExit("Use an http(s) board URL.")
        try:
            tabs = operate(board_id(args.url), {"kind": "get_viewport"}, 1, collect=True)["tabs"]
        except SystemExit:
            tabs = 0
        if tabs:
            print(json.dumps({"ok": True, "url": args.url, "tabs": tabs, "alreadyOpen": True}))
            return
        opened = webbrowser.open(args.url)
        result = {"ok": opened, "url": args.url, **wait_ready(board_id(args.url), 15)} if opened else {"ok": False, "url": args.url}
    elif args.command == "wait":
        result = wait_ready(board_id(args.board), args.seconds)
    elif args.command == "health":
        result = call("/health")
    elif args.command == "snapshot":
        reply = operate(board_id(args.board), {"kind": "take_snapshot"})
        match = re.fullmatch(r"data:image/png;base64,(.+)", (reply.get("snapshot") or {}).get("dataUrl", ""), re.S)
        if not match:
            raise SystemExit("Board did not return a PNG snapshot.")
        image = base64.b64decode(match.group(1))
        snapshot = reply.pop("snapshot")
        crop, bounds = None, snapshot.get("bounds")
        if args.region and bounds:
            crop, bounds = crop_box(bounds, *png_size(image), args.region)
        image = shrink_png(image, None if args.full else args.max_side, crop)
        with open(args.png, "wb") as file:
            file.write(image)
        width, height = png_size(image)
        result = {**reply, "bounds": bounds, "width": width, "height": height, "image_file": args.png}
    elif args.command == "tabs":
        result = operate(board_id(args.board), {"kind": "get_viewport"}, 1, collect=True)
    elif args.command == "viewport":
        result = operate(board_id(args.board), {"kind": "get_viewport"})
    elif args.command == "pan":
        board = board_id(args.board)
        result = operate(board, {"kind": "set_viewport", **fit_region(board, args.left, args.top, args.right, args.bottom)})
    else:
        operation = {"kind": "get_zoom"} if args.percent is None else {"kind": "set_zoom", "level": args.percent}
        result = operate(board_id(args.board), operation)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
