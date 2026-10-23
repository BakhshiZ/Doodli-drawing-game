import asyncio
from typing import Literal
import json
import random
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

WORDS = [
    "house", "tree", "bicycle", "pizza", "rocket", "guitar", "elephant", "castle",
    "umbrella", "sunglasses", "volcano", "robot", "snowman", "lighthouse", "dragon",
    "bridge", "penguin", "teapot", "airplane", "cactus", "headphones", "mountain",
    "spider", "pirate", "sandwich", "clock", "butterfly", "ladder", "campfire", "whale",
]

TURN_SECONDS = 60
INTERMISSION_SECONDS = 4
MIN_PLAYERS = 2
# Max strokes stored is about 3600 (60 events / sec for 60s so make buffer a bit more)
MAX_STROKES = 4_000
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
STATIC_DIR = Path(__file__).parent / "static"
LOGIN_PATH = STATIC_DIR / "html" / "login_page.html"
GAME_PATH = STATIC_DIR / "html" / "game_page.html"


class Player:
    def __init__(self, websocket: WebSocket, name: str):
        self.id = uuid.uuid4().hex[:8]
        self.websocket = websocket
        self.name = name
        self.score = 0
        self.has_guessed = False


class Game:
    def __init__(self):
        self.players: list[Player] = []
        self.phase: Literal["waiting", "drawing", "intermission"] = "waiting"
        self.drawer: Player | None = None
        self.word: str | None = None
        self.strokes: list[dict] = []
        self.turn_started_at = 0.0
        self.next_drawer_index = -1
        self.background_task: asyncio.Task | None = None


    async def send(self, player: Player, message: dict):
        try:
            await player.websocket.send_text(json.dumps(message))
        except Exception:
            pass

    async def broadcast(self, message: dict, exclude: Player | None = None):
        for player in list(self.players):
            if player is not exclude:
                await self.send(player, message)

    def time_left(self) -> float:
        if self.phase != "drawing":
            return 0.0
        return max(0.0, TURN_SECONDS - (time.monotonic() - self.turn_started_at))

    async def broadcast_state(self):
        hint = ""
        if self.phase == "drawing" and self.word:
            hint = " ".join("_" if c.isalpha() else c for c in self.word)
        await self.broadcast({
            "type": "state",
            "phase": self.phase,
            "drawer_id": self.drawer.id if self.drawer else None,
            "hint": hint,
            "time_left": round(self.time_left(), 1),
            "players": [
                {"id": p.id, "name": p.name, "score": p.score, "guessed": p.has_guessed}
                for p in self.players
            ],
        })

    async def add_player(self, websocket: WebSocket, raw_name: str) -> Player:
        name = raw_name.strip()[:20] or f"Player{len(self.players) + 1}"
        player = Player(websocket, name)
        self.players.append(player)

        await self.send(player, {"type": "joined", "id": player.id})
        await self.send(player, {"type": "history", "strokes": self.strokes})
        await self.broadcast({"type": "system", "text": f"{player.name} joined"})
        await self.broadcast_state()

        if self.phase == "waiting" and len(self.players) >= MIN_PLAYERS:
            await self.start_turn()
        return player

    async def remove_player(self, player: Player):
        if player not in self.players:
            return
        was_drawer = player is self.drawer
        self.players.remove(player)
        await self.broadcast({"type": "system", "text": f"{player.name} left"})

        if len(self.players) < MIN_PLAYERS:
            self.cancel_background_task()
            self.phase = "waiting"
            self.drawer = None
            self.word = None
            self.strokes = []
            await self.broadcast({"type": "clear"})
            await self.broadcast({"type": "system", "text": "Waiting for more players"})
            await self.broadcast_state()
        elif was_drawer and self.phase == "drawing":
            await self.end_turn("The drawer left.")
        else:
            await self.broadcast_state()

    def cancel_background_task(self):
        task = self.background_task
        if task and task is not asyncio.current_task():
            task.cancel()
        self.background_task = None

    async def start_turn(self):
        if len(self.players) < MIN_PLAYERS:
            self.phase = "waiting"
            await self.broadcast_state()
            return

        self.next_drawer_index = (self.next_drawer_index + 1) % len(self.players)
        self.drawer = self.players[self.next_drawer_index]
        self.word = random.choice(WORDS)
        self.strokes = []
        for p in self.players:
            p.has_guessed = False

        self.phase = "drawing"
        self.turn_started_at = time.monotonic()

        await self.broadcast({"type": "clear"})
        await self.send(self.drawer, {"type": "word", "word": self.word})
        await self.broadcast({"type": "system", "text": f"{self.drawer.name} is drawing"})
        await self.broadcast_state()

        self.cancel_background_task()
        self.background_task = asyncio.create_task(self._turn_timer())

    async def _turn_timer(self):
        await asyncio.sleep(TURN_SECONDS)
        await self.end_turn("Time is up.")

    async def end_turn(self, reason: str):
        if self.phase != "drawing":
            return
        self.cancel_background_task()
        revealed = self.word
        self.phase = "intermission"
        self.drawer = None
        self.word = None
        await self.broadcast({"type": "system", "text": f"{reason} The word was “{revealed}”."})
        await self.broadcast_state()
        self.background_task = asyncio.create_task(self._intermission())

    async def _intermission(self):
        await asyncio.sleep(INTERMISSION_SECONDS)
        await self.start_turn()

    async def handle_draw(self, player: Player, msg: dict):
        if player is not self.drawer or self.phase != "drawing":
            return
        try:
            stroke = {
                "type": "draw",
                "x0": float(msg["x0"]), "y0": float(msg["y0"]),
                "x1": float(msg["x1"]), "y1": float(msg["y1"]),
                "color": msg["color"] if COLOR_RE.match(str(msg.get("color", ""))) else "#1b1b2f",
                "size": max(1, min(30, int(msg.get("size", 4)))),
            }
        except (KeyError, ValueError, TypeError):
            return
        if len(self.strokes) < MAX_STROKES:
            self.strokes.append(stroke)
        await self.broadcast(stroke, exclude=player)

    async def handle_clear(self, player: Player):
        if player is not self.drawer or self.phase != "drawing":
            return
        self.strokes = []
        await self.broadcast({"type": "clear"})

    async def handle_guess(self, player: Player, text: str):
        text = text.strip()[:100]
        if not text:
            return

        can_guess = (
            self.phase == "drawing"
            and player is not self.drawer
            and not player.has_guessed
        )

        if can_guess and text.lower() == self.word.lower():
            # faster guess = more points
            fraction_left = self.time_left() / TURN_SECONDS
            player.score += 50 + int(50 * fraction_left)
            self.drawer.score += 25
            player.has_guessed = True
            await self.broadcast({"type": "system", "text": f"{player.name} guessed the word"})
            await self.broadcast_state()

            guessers = [p for p in self.players if p is not self.drawer]
            if all(p.has_guessed for p in guessers):
                await self.end_turn("Everyone guessed it.")
            return

        # prevent leaking of word
        if self.phase == "drawing" and self.word and (
            player is self.drawer or player.has_guessed
        ):
            if self.word.lower() in text.lower():
                await self.send(player, {"type": "system", "text": "You can not share the word."})
                return

        await self.broadcast({"type": "chat", "name": player.name, "text": text})

app = FastAPI()
game = Game()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def login_page():
    return HTMLResponse(LOGIN_PATH.read_text(encoding="utf-8"))


@app.get("/game")
async def game_page():
    return HTMLResponse(GAME_PATH.read_text(encoding="utf-8"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    player: Player | None = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue

            kind = msg.get("type")
            if kind == "join" and player is None:
                player = await game.add_player(websocket, str(msg.get("name", "")))
            elif player is None:
                continue
            elif kind == "draw":
                await game.handle_draw(player, msg)
            elif kind == "clear":
                await game.handle_clear(player)
            elif kind == "guess":
                await game.handle_guess(player, str(msg.get("text", "")))
    except WebSocketDisconnect:
        pass
    finally:
        if player is not None:
            await game.remove_player(player)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend:app", host="localhost", port=8000, reload=True)