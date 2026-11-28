# VoidFeed Studio

**VoidFeed Studio** is the integrated publishing and content-management workspace behind **VoidFeed | خوراکِ خلأ**.

It combines a web-based Studio with a Telegram bot. The bot is one part of the product, not a separate project.

## Main components

- FastAPI Studio backend
- Browser interface and Telegram Mini App
- Telegram bot and publishing workflows
- Content generation and provider integrations
- Media generation and validation
- News and moderation modules
- Shared SQLite database layer
- Optional tunnel and DNS utilities
- Automated tests

## Project structure

| Path | Purpose |
|---|---|
| `studio.py` | Studio API |
| `studio_web/` | Web interface, assets and documentation |
| `bot.py` | Telegram bot |
| `voidfeed_db.py` | Shared database layer |
| `contentgen.py` | Content generation |
| `mediagen.py` | Media generation |
| `media_validate.py` | Media validation |
| `newsbot.py` | News workflows |
| `moderator.py` | Moderation |
| `providers.py` | Provider integrations |
| `tests/` | Automated tests |

## Requirements

- Python 3.14 (current tested development environment)
- Node.js for JavaScript tests
- Telegram credentials for bot functionality
- ffmpeg for workflows that require media processing

Compatibility with other Python versions has not yet been verified.

## Installation

Clone the repository, create a Python virtual environment, and install dependencies:

    git clone https://github.com/johnnywish78/VoidFeedBot.git
    cd VoidFeedBot
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements.txt
    cp .env.example .env

Edit `.env` with the credentials and settings required by your installation. Never commit real credentials.

## Running

Start the Studio API:

    uvicorn studio:app --host 127.0.0.1 --port 8077

Start the Telegram bot separately when its configuration is ready:

    python bot.py

The Studio supports Telegram Web App authentication. Standalone browser authentication requires secure server-side configuration.

## Tests

Run the Python tests:

    python -m unittest discover -s tests -v

Run the JavaScript Studio test:

    node tests/test_studio_boot.cjs

Use isolated test data, never production databases.

## Security

Do not commit `.env`, API keys, bot tokens, private keys, production databases, user uploads or backups. Keep deployment credentials outside the repository.

## Development status

VoidFeed Studio is under active development. Features and integrations may change; verify the current code and tests before production use.

## License

No open-source license is currently provided. Public visibility does not grant permission to reuse, modify, redistribute or commercially exploit this code. All rights remain reserved by the respective rights holders.
