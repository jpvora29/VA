"""Deprecated entrypoint — QBR Studio is now a tab of the one application.

Studio and the Chatbot were merged into a single Dash app with one navbar
(``app.py``). This file stays so that ``python authoring_app.py`` keeps working: it
launches the merged app, which lands on Studio.

    python authoring_app.py   →   http://localhost:8131   (Studio tab)
"""
from __future__ import annotations

from app import app

if __name__ == "__main__":
    import os

    from studio.serve import run_app

    print("authoring_app.py is deprecated — run `python app.py` instead.\n")
    run_app(
        app,
        port=int(os.environ.get("PORT", "8131")),
        debug=True,
        dev_tools_hot_reload=False,
    )
