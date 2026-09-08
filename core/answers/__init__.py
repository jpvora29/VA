"""What an answer carries besides its prose.

An answer is a paragraph until you can check it. These modules build the record
that makes it checkable: the figures it states (:mod:`core.answers.figures`), and
where each one came from (:mod:`core.answers.provenance`) — the scope it was run
under, the queries behind it, the business definitions it used, and whether every
number in the prose is actually present in the evidence.

Pure: no LLM, no database. The graph hands in a finished turn; these return a
record the UI renders.
"""
