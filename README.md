# Doodli

A real-time multiplayer drawing and guessing game inspired by Skribbl.io, built with FastAPI, asyncio, and WebSockets.

Players can join game rooms, take turns drawing a selected word, and compete to guess what others are drawing in real-time.

Built with FastAPI and WebSockets on the backend, plain HTML, CSS and JavaScript on the frontend. There is a single room, and all state lives in memory.

## Requirements

- Python 3.10+
- The packages in `requirements.txt` (`fastapi`, `uvicorn[standard]`)

## Getting started with the game

1. Clone the repository
2. Create a virtual environment `python -m venv .venv`
3. Activate the environment `.venv/Scripts/activate`
4. Install required dependencies `pip install -r requirements.txt`
5. Run the code `python -m backend`

Then open http://localhost:8000 in two or more browser windows, enter a name in each and join. The game will automatically begin when at least two players are in the room.

## Scoring information

A correct guess scores `50` plus up to `50` bonus points depending on how much time is left and the drawer receives `25` points for each correct guesser.

## Project structure

```
backend.py FastAPI app, WebSocket game logic
requirements.txt Python dependencies
static/
html/
login_page.html Username entry, served at /
canvas_page.html Game screen, served at /game
css/
login.css Styles for the login page
canvas.css Styles for the game page

```

## Routes and their purposes

| Route         | Purpose                                                         |
| ------------- | --------------------------------------------------------------- |
| `/`           | Login Page                                                      |
| `/game`       | Game page (redirects you to `/` if you have not set a username) |
| `/ws`         | The WebSocket used by the game                                  |
| `/static/...` | CSS and html static files                                       |

## Constants

These are found at the top of `backend.py`

- `WORDS`: The list of words to draw
- `TURN_SECONDS`: The length of a round, defaulted to 60 seconds
- `INTERMISSION_SECONDS`: The pause between rounds, defaulted to 4 seconds
- `MIN_PLAYERS`: Minimum number of players to start, defaulted to 2
