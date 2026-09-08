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

## Signing in

Point the app at any OpenID Connect provider and it signs people in there instead of
asking for a name. One generic client covers Microsoft Entra ID, Okta, Google Workspace
and Auth0 — the issuer is the only thing that differs.

```bash
OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0   # or your Okta/Google/Auth0 issuer
OIDC_CLIENT_ID=<application (client) id>
OIDC_CLIENT_SECRET=<client secret>
OIDC_PROVIDER_NAME=Microsoft        # optional — the words on the button
FLASK_SECRET_KEY=<a long random string>   # signs the session cookie; REQUIRED in production
```

Register `https://<your-host>/auth/callback` as the redirect URI with the provider. Behind
a proxy that terminates TLS, set `OIDC_REDIRECT_URI` to that exact URL — otherwise it is
derived from the request and will be the internal `http://` one.

Accounts are keyed on the email address the provider vouches for, so somebody who used the
old name-based sign-in with their address keeps their chats. Optional: `OIDC_SCOPES`
(default `openid email profile`) and `OIDC_INSECURE_TRANSPORT=1`, which drops the `Secure`
flag on the session cookie so the real flow can be tested over `http://localhost`.

**With none of those set the app falls back to the original username-only sign-in**, which
is what keeps a local run and the test suite working. It is not a deployment mode: anyone
who can reach the address can sign in as anyone, and the sign-in card says so.

MoM's engine is `mom/` (no Dash), driven by `ui/mom/`. A run takes the meeting note and
the deck it was about, tags both against `mom/data/tag_list.csv`, scores the priority
topics, verifies them, and writes the minutes. Each run owns a directory under
`outputs/mom/` holding its inputs, intermediate JSON, the .docx and a token log. It uses
the application's Azure deployment (`core/llm/clients.py`), so there is no second key to
set; point `MOM_TAG_LIST` at another .csv/.xlsx to tag against a different vocabulary.

The shell itself (navbar, panes, the left rail every workspace shares) is `ui/shell/`.
`authoring_app.py` is a deprecated alias kept for muscle memory — it launches the same
app on port 8131.
