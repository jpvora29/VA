"""QBR Studio authoring workspace — the callback layer for ``authoring_app.py``.

The top-level ``authoring_app.py`` reads like a table of contents: it creates the
app, sets the layout, then registers each group of callbacks. The actual work
lives here, one concern per module:

    config      shared constants + the single DB engine
    generate    build a deck / template-doc from a selection (pure helpers)
    layout      create the Dash app and its page shell
    navigation  move between modes, slides, tabs, library panels
    setup       Generate the deck, live scope preview
    editing     edit fields, pages, widgets, colors on the canvas
    export      fill/assemble the template and download the .pptx
"""
