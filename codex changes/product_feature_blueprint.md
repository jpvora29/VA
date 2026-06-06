# Virtual Analyst Product Feature Blueprint

## Purpose

This document consolidates the proposed product features for turning Virtual
Analyst into a governed insurance analytics, executive storytelling, decision,
and presentation workspace.

The design principle is:

> Explore data deterministically, use AI for interpretation and storytelling,
> let users control decisions and presentation content, and preserve evidence
> throughout the workflow.

This is reference material only. Nothing in this document is connected to the
current runtime.

## Product Experience

The proposed product flow is:

1. Explore governed insurance data in the Analytics Playground.
2. Save useful pivots, tables, charts, and observations as analysis artifacts.
3. Ask AI to interpret only the selected and bounded evidence.
4. Assemble evidence into editable Boardroom pages.
5. Use Storytelling Mode to create an executive narrative.
6. Review facts, recommendations, risks, and decisions separately.
7. Record approved decisions and actions on the Decision Board.
8. Export the approved document to PowerPoint.

Normal chat should remain available and unchanged. Advanced modes should be
explicitly launched from the plus menu or another clearly identified workspace.

---

## 1. Boardroom Mode

Boardroom Mode converts an analytical answer into an executive-ready,
multi-page visual summary.

### Existing and Proposed Content

- Executive headline
- KPI cards
- Executive insights
- Editable commentary
- Risks and watch items
- Charts and comparisons
- Opportunity radar
- Market opportunity map
- What changed over time
- Carrier health score
- Peer positioning matrix
- Carrier battlecards
- Supporting evidence
- Decision required
- Recommended actions

### Boardroom Responsibilities

- Present evidence-backed findings clearly.
- Separate observed facts from interpretation and recommendations.
- Preserve filters, metric definitions, and data lineage.
- Allow users to refine presentation content without changing source evidence.
- Serve as the working document used by Storytelling Mode and PPT export.

Boardroom Mode should not become the permanent system of record for decisions.
Approved decisions belong in the Decision Board.

---

## 2. Editable Boardroom Widgets

Every Boardroom widget should support an explicit Edit Mode.

### Editable Properties

- Title and subtitle
- Displayed value
- Labels and annotations
- Commentary
- Colors from an approved theme
- Chart type from a compatible set
- Sort order
- Visible series
- Widget size and position
- Inclusion in Boardroom and PowerPoint

### Generated and Edited Values

Manual edits must never overwrite the original generated evidence. Each field
should retain both values:

```json
{
  "generated_value": "12.4%",
  "display_value": "12.1%",
  "source": "user_override",
  "edited_by": "user_id",
  "edited_at": "timestamp",
  "reason": "Validated against the finance report"
}
```

### Required Controls

- Edit
- Save
- Cancel
- Reset to generated value
- Duplicate widget
- Hide from presentation
- Delete user-created widget
- View source evidence
- View revision history

### Integrity Rules

- User-entered numbers must display an `Edited` indicator.
- Generated evidence remains immutable.
- Manual values are not automatically learned as factual memory.
- AI cannot silently replace a user override.
- Exported presentations should optionally include an audit appendix.

---

## 3. Page and Slide Builder

Users should be able to build a Boardroom document similarly to assembling a
controlled presentation.

### Page Actions

- Add a blank page
- Add a page from a template
- Duplicate an existing page
- Rename a page
- Reorder pages
- Delete a page
- Lock an approved page
- Hide a page from export
- Add speaker notes

### Layout Behavior

- Use a governed grid instead of unrestricted free-form positioning.
- Support drag, resize, align, distribute, and snap-to-grid.
- Provide responsive Boardroom layouts and fixed PowerPoint layouts.
- Prevent overlapping widgets.
- Warn when content will overflow during export.

### Page Templates

- Executive summary
- Performance overview
- What changed
- Risk review
- Opportunity review
- Peer comparison
- Strategic choices
- Recommendations
- Decisions required
- Action plan
- Appendix
- Blank slide

---

## 4. User-Only Widget Library

The widget library should include components that users can add manually. These
widgets do not need to be available to the LLM.

### Executive Widgets

- Executive takeaway
- Key message
- Decision required
- Decision and rationale
- Strategic priorities
- Recommendation
- Assumptions and caveats
- Quote or customer voice

### Planning Widgets

- Action tracker
- Owner and deadline table
- Milestone roadmap
- Dependency map
- Initiative portfolio
- Success measures
- Next meeting and review date

### Analytical Widgets

- KPI card
- Target versus actual
- Variance bridge
- Financial bridge
- Scenario comparison
- Ranking table
- Risk register
- Opportunity pipeline
- SWOT
- Two-by-two matrix
- Heat map
- Funnel
- Waterfall
- Timeline
- Appendix table

### Content Widgets

- Rich text
- Image
- Logo
- Divider
- Section title
- Footnote
- Source note
- Attachment link

Designers should own widget templates, spacing, typography, themes, and export
behavior. Business users should primarily control content.

---

## 5. Analytics Playground

The Analytics Playground is a deterministic no-code environment for business
users to explore GPR and Survey data before involving AI.

### Data Selection

- Dataset: GPR or Survey
- One or multiple countries
- One or multiple carriers
- One or multiple years
- Product, industry, segment, section, attribute, or other valid dimensions
- Governed metric and measure selection

### Pivot Builder

- Drag dimensions into Rows and Columns
- Add one or more Values
- Select aggregation
- Add filters
- Sort and rank
- Top-N and Bottom-N
- Year-over-year variance
- Absolute and percentage change
- Share and contribution calculations
- Conditional formatting
- Totals and subtotals
- Table and chart preview
- Drill into supporting records where permitted

### Saved Analysis

Users can:

- Save a view
- Duplicate a view
- Share a view
- Add it to Boardroom
- Export it to Excel
- Ask AI to interpret it
- Convert it into a reusable widget

### Governed Semantic Layer

The Playground must use the Flow Registry and metric definitions rather than
letting users combine arbitrary columns.

It should enforce:

- Compatible dimensions and measures
- Approved aggregation rules
- GPR and Survey separation
- Carrier and peer confidentiality
- Minimum sample-size rules
- Valid year and category handling
- Row and query limits
- Metric definitions and formatting

### Analysis Artifact

Each saved exploration should produce a reusable artifact:

```json
{
  "artifact_id": "analysis_123",
  "dataset": "gpr",
  "filters": {
    "country": ["Canada"],
    "carrier": ["Carrier A"],
    "year": [2023, 2024, 2025]
  },
  "dimensions": ["year", "product"],
  "measures": ["premium"],
  "aggregation": {"premium": "sum"},
  "result_snapshot": [],
  "visualization": {},
  "lineage": {},
  "user_overrides": []
}
```

This artifact is the contract between the Playground, AI, Boardroom, and PPT
export.

---

## 6. AI-Assisted Analysis

AI should operate on selected analysis artifacts and bounded evidence, not on an
unrestricted dump of the complete dataset.

### AI Capabilities

- Explain material movements
- Compare selected carriers, countries, years, or products
- Identify evidence-backed risks and opportunities
- Detect meaningful tensions between metrics
- Recommend a compatible chart
- Draft executive commentary
- Suggest follow-up analyses
- Create a proposed Boardroom page

### User Control

- AI must preserve the user's pivot specification and filters.
- AI-proposed widgets require approval before insertion.
- Users can pin mandatory evidence.
- Users can exclude findings.
- Users can regenerate one section without changing approved content.
- User edits always take precedence over subsequent AI generation.

### Evidence Rules

- Every factual claim links to evidence.
- Recommendations are labelled separately from facts.
- Unsupported causality is prohibited or clearly qualified.
- Conflicting evidence is shown as a tension.
- Missing evidence is disclosed rather than invented.

---

## 7. Storytelling Mode

Storytelling Mode is the orchestration layer between analysis artifacts and the
Boardroom Composer. It creates a coherent executive narrative rather than a
collection of unrelated widgets.

### Story Setup

The user selects:

- Audience
- Meeting purpose
- Narrative tone
- Presentation duration
- Strategic focus
- Mandatory evidence
- Required decisions
- Existing Boardroom pages and analysis artifacts

### Audience Examples

- Executive committee
- Carrier leadership
- Client meeting
- Renewal strategy team
- Growth planning team
- Risk committee
- Technical analytics team

### Story Arc

A strong default sequence is:

1. Executive headline
2. Current position
3. What changed
4. Why it matters
5. Risks
6. Opportunities
7. Peer position
8. Strategic choices and trade-offs
9. Recommended actions
10. Decision required

### Storytelling Controls

- Five-minute, fifteen-minute, or detailed version
- Decisive, analytical, persuasive, or neutral tone
- Reorder chapters
- Lock approved chapters
- Regenerate one page
- Add or remove evidence
- Change the emphasis without changing facts
- Generate speaker notes
- Generate anticipated executive questions
- Create an appendix from unused evidence

### Execution Content

The final story should support action by including:

- Decision required
- Recommended action
- Owner
- Due date
- Expected impact
- Success measure
- Dependency
- Risk and mitigation
- Follow-up date

Approved decisions and actions can be pinned to the Decision Board.

---

## 8. Decision Board

The Decision Board is a non-LLM workspace for recording and tracking business
decisions. It should be accessible from the sidebar.

### Board Appearance

Decisions appear as color-coded sticky notes:

- Green: approved
- Yellow: under review
- Red: blocked or rejected
- Blue: planned
- Grey: archived

### Decision Contents

- Decision statement
- Business rationale
- Discussion points
- Owner
- Stakeholders
- Status
- Priority
- Decision date
- Review date
- Actions and due dates
- Supporting evidence
- Linked chats
- Linked Boardroom pages
- Linked analysis artifacts
- Attachments
- Revision history

### User Actions

- Create manually without calling the LLM
- Pin a Boardroom insight, risk, opportunity, or recommendation
- Search and filter
- Drag between statuses
- Comment and mention colleagues
- Reopen a decision
- Archive a decision
- Export selected decisions
- Add a decision widget to Boardroom

### Optional AI Action

`Ask Agent About This Decision` should explicitly pass only the selected
decision and approved linked evidence to AI.

Business decisions must not silently become agent facts or episodic memory.

---

## 9. Feedback and Episodic Memory

Thumbs-up and thumbs-down should support optional written feedback.

### Feedback Interaction

After thumbs-down, show:

- A compact text field: `What was wrong?`
- Category chips
- Optional field: `What should it have done?`
- Submit and cancel actions

### Feedback Categories

- Wrong data
- Wrong calculation
- Incorrect chart
- Wrong filters
- Poor routing
- Missing context
- Unsupported claim
- Unhelpful recommendation
- Tone or formatting
- Other

### Stored Context

- Rating and written feedback
- User and tenant
- Conversation and message
- Question and answer
- Route and selected skills
- SQL and tool calls
- Filters and data scope
- Chart specification
- Evidence references
- Expected correction

### Uses

- Retrieve relevant past corrections for similar requests
- Improve skill and route selection
- Avoid repeated SQL or chart mistakes
- Create regression tests
- Identify weak prompts, datasets, tools, and workflows
- Learn user presentation preferences

### Safeguards

- Separate preferences from factual corrections.
- Validate corrections before treating them as truth.
- Apply tenant isolation.
- Support deletion, editing, expiration, and audit.
- Retrieve only semantically relevant memories.
- Measure whether retrieved feedback improves later answers.
- Never store sensitive data without the required controls.

---

## 10. PowerPoint Output

PowerPoint export should render the final approved Boardroom document rather than
re-generating content independently.

### Export Requirements

- Use the same page and widget schemas as the UI.
- Preserve user overrides.
- Preserve approved layouts.
- Include speaker notes where selected.
- Include sources and footnotes.
- Support cover, section, content, decision, action, and appendix slides.
- Validate overflow, clipping, contrast, and font size.
- Produce a pre-export preview.
- Allow export of selected pages.

### Presentation Enrichment

The exported deck can combine:

- AI-generated analytical widgets
- User-created widgets
- Playground pivots
- Boardroom visuals
- Storytelling narrative
- Decisions and action plans
- Manual images, text, and appendices

### Auditability

Optionally include:

- Data lineage appendix
- Filter definitions
- Metric definitions
- User override report
- Evidence-to-claim mapping
- Generation and edit timestamps

---

## 11. Design Team Governance

The product should augment the design team, not replace it.

### Design Team Ownership

- Brand system
- Themes
- Typography
- Color and accessibility standards
- Page templates
- Widget templates
- Grid and layout rules
- PowerPoint masters
- External presentation standards
- Approval of new visual components

### Business User Ownership

- Analysis selection
- Narrative emphasis
- Figures and corrections
- Decisions
- Actions
- Presentation assembly within approved templates

### Guardrails

- Designers can lock templates, pages, widgets, and fields.
- AI cannot invent unapproved visual styles.
- Brand tokens are centrally controlled.
- External and high-stakes decks can require design review.
- Include a `Send to Design` workflow.
- Capture frequently requested custom layouts for design-system improvement.

This shifts repetitive formatting to the product while preserving the design
team's ownership of visual quality, storytelling craft, brand governance, and
exceptional presentations.

---

## 12. Suggested Architecture

Keep the major capabilities separate:

### Analytics Playground

Deterministic filters, pivots, calculations, queries, and lineage.

### AI Analysis

Evidence-grounded interpretation and visual recommendations.

### Boardroom Composer

Editable pages, widget instances, layout, overrides, and approvals.

### Storytelling Engine

Narrative planning, sequencing, recommendations, and speaker notes.

### Decision Service

Durable decisions, actions, comments, ownership, and audit history.

### Feedback Memory Service

Structured feedback, retrieval, correction validation, and evaluation.

### Presentation Renderer

Schema-driven PowerPoint generation and visual validation.

### Core Schemas

- `AnalysisArtifact`
- `BoardroomDocument`
- `BoardroomPage`
- `WidgetTemplate`
- `WidgetInstance`
- `FieldValue`
- `EvidenceReference`
- `UserOverride`
- `StoryPlan`
- `DecisionRecord`
- `ActionItem`
- `FeedbackRecord`
- `Revision`

The UI and PowerPoint renderer should consume the same approved document model.
This avoids separate implementations drifting apart.

---

## 13. Recommended Delivery Phases

### Phase 1: Boardroom Editing

- Widget edit mode
- Generated versus overridden values
- Reset and revision history
- Page reorder, duplicate, hide, and rename

### Phase 2: Page and Widget Builder

- Blank and templated pages
- User-only widget library
- Governed drag, resize, and layout
- Shared Boardroom document schema

### Phase 3: PowerPoint Export

- Render approved document
- Preview and overflow validation
- Sources, notes, and audit appendix

### Phase 4: Analytics Playground

- GPR and Survey selectors
- Multi-country, carrier, and year filters
- Governed pivot builder
- Saved analysis artifacts

### Phase 5: AI and Storytelling

- Interpret selected artifacts
- Build evidence-backed story plans
- Create proposed pages and speaker notes
- User approval and page locking

### Phase 6: Decision Board

- Manual decision records
- Pin from Boardroom
- Actions, owners, review dates, and comments
- Insert decision widgets into presentations

### Phase 7: Feedback Memory

- Written thumbs feedback
- Structured failure categories
- Relevant memory retrieval
- Regression eval creation
- Improvement measurement

---

## 14. Success Measures

- Time from question to executive-ready presentation
- Percentage of Boardroom pages accepted without major edits
- Percentage of claims with valid evidence links
- Number of repeated analyses reused as artifacts
- User overrides by type and cause
- Reduction in repeated agent errors
- Decision follow-through rate
- PPT export success without layout defects
- Design review time spent on strategic work versus repetitive formatting
- Weekly active business leaders
- Return usage of Playground, Boardroom, and Decision Board

## Final Product Positioning

Virtual Analyst should not be positioned as an autonomous presentation designer
or an unrestricted AI analytics system.

It should be positioned as:

> A governed insurance intelligence workspace where users explore trusted data,
> collaborate with AI on interpretation and narrative, make accountable
> decisions, and produce brand-approved executive presentations.

