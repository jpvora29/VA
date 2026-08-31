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
| **MoM**     | Minutes of meeting — placeholder, not built yet  | `ui/mom/`                   |

Studio is the landing workspace. One sign-in covers all four; switching tabs hides a
workspace rather than unmounting it, so an in-progress deck or chat survives the move.

The shell itself (navbar, panes, the left rail every workspace shares) is `ui/shell/`.
`authoring_app.py` is a deprecated alias kept for muscle memory — it launches the same
app on port 8131.
