"""The application shell: one navbar over four workspaces.

    tabs         the four workspaces, as data
    rail         the left-rail frame every workspace shares (a leaf: dash only)
    navbar       the top bar (brand, tabs, signed-in user)
    placeholder  the frame a not-yet-built workspace wears
    stores       every dcc.Store the merged app keeps alive
    panes        one builder per workspace + the dispatch table
    router       tab click -> active-tab -> pane visibility
    layout       root_layout (what app.py assigns) and app_shell

Deliberately empty of imports. ``studio.page.authoring.chrome`` imports
``ui.shell.rail`` to build Studio's rail in the shared frame; re-exporting the
heavier modules here would drag the whole Chatbot into that import and turn a
leaf dependency into a cycle. Import the module you need.
"""
