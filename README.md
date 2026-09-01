# Virtual-Analyst

## Running the app

```bash
python app.py     # http://localhost:8080
```

One Dash application with four workspaces behind a single navbar, in this order:

| Tab         | What it does                                    | Lives in                    |
| ----------- | ----------------------------------------------- | --------------------------- |
| **Studio**  | Build a QBR deck (Setup → Data → Canvas → Review)| `studio/`                   |
| **Chatbot** | Ask the Virtual Analyst; Decision Board          | `ui/`, `core/`              |
| **Recap**   | Period recap — placeholder, not built yet        | `ui/recap/`                 |
| **MoM**     | Meeting note + QBR deck → minutes (.docx)        | `ui/mom/`, `mom/`           |

Studio is the landing workspace. One sign-in covers all four; switching tabs hides a
workspace rather than unmounting it, so an in-progress deck or chat survives the move —
and a MoM run keeps going while you are looking at something else.

MoM's engine is `mom/` (no Dash), driven by `ui/mom/`. A run takes the meeting note and
the deck it was about, tags both against `mom/data/tag_list.csv`, scores the priority
topics, verifies them, and writes the minutes. Each run owns a directory under
`outputs/mom/` holding its inputs, intermediate JSON, the .docx and a token log. It uses
the application's Azure deployment (`core/llm/clients.py`), so there is no second key to
set; point `MOM_TAG_LIST` at another .csv/.xlsx to tag against a different vocabulary.

The shell itself (navbar, panes, the left rail every workspace shares) is `ui/shell/`.
`authoring_app.py` is a deprecated alias kept for muscle memory — it launches the same
app on port 8131.
