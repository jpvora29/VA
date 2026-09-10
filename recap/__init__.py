"""Business Review Recap — historical QBR decks in, one auditable recap out.

Pipeline stages:
  1. Raw PPT Extraction
  2. Noise Filtering (rule-based + LLM ambiguous pass)
  3. Semantic Content Units
  4. Business Glossary (dynamic term retrieval)
  5. Metadata / Semantic Enrichment (LLM)
  6. Umbrella Classification — 4 independent Boolean LLMs
  7. Sub-category Classification
  8. Action Item Classification
  9. Structured Insight Store
  10. Recap Generation
  11. PPTX rendering into the QBR Recap template

The workspace calls :func:`recap.run.run_recap_pipeline`, which owns the order above
and the files a run writes; ``recap.pipeline.BusinessReviewPipeline`` owns one deck's
journey through stages 1-9. The model client, and therefore the credentials, come from
``core.llm.clients`` — the same ones Studio, the Chatbot and MoM use.

    from recap.run import RecapRequest, run_recap_pipeline

    result = run_recap_pipeline(request)
    print(result.pptx_path)

``recap.main`` is the command-line entry point for the same flow.
"""
