# Virtual Analyst: Complete Product Roadmap

**Status:** Master product direction and validation document. It consolidates every idea discussed for the chatbot, Boardroom, Studio, Recap, MoM, Decision Board, enterprise readiness, and commercial packaging. No application code is changed by this document.

**Date:** 7 September 2026

## Executive summary

Virtual Analyst should not be sold as another analytics chatbot. Its stronger position is:

> A governed Insurance QBR Copilot that turns the same trusted data into an answer, an executive slide, a decision, and a follow-up without changing the meaning of the numbers.

The product already has the core pieces: governed analytics, conversational answers, charts and underlying rows, QBR generation, editable Boardroom output, PowerPoint export, a Decision Board, and Minutes of Meeting generation. The next product step is to connect these capabilities into one obvious workflow and remove measures that a business audience cannot explain.

The Boardroom direction proposed in this document is one important workstream, not the whole roadmap. Opaque AI-generated labels such as `High`, `Med`, and `Low`, or normalized opportunity scores such as `70` and `80`, should not be primary business measures. They should be replaced by premium, share of wallet, change over a named period, variance to an approved benchmark, and a visible reason for any classification.

## Complete idea register

This is the canonical checklist of ideas covered by the roadmap.

| Product area | Ideas included |
| --- | --- |
| Positioning | Governed Insurance QBR Copilot; sell an end-to-end outcome rather than a generic chatbot |
| Chatbot experience | Context-aware questions, command shortcuts, visible scope, tailored follow-ups, account memory, evidence, recovery guidance |
| Trust | Calculation panel, metric definitions, filters, freshness, evidence rows, verification states, verified-answer library |
| From answer to action | Explore, add to QBR, create slide, pin to Boardroom, create decision, assign action, export, share, watch |
| Proactive productivity | Metric watchlists, material-change alerts, periodic briefings, pre-QBR preparation, overdue-action reminders |
| Portfolio command centre | Watched accounts, material movements, whitespace, upcoming QBRs, stale data, decisions and actions in one home view |
| Boardroom | Explainable risk watchlist, Product Line Headroom, Quarterly Performance, Industry Whitespace, actual-measure positioning, filters |
| Studio and presentation | Evidence-consistent slides, editable output, reusable customer templates, matching screen and PowerPoint semantics |
| Recap | One-page executive brief, three numbers that matter, risks, whitespace, decisions, actions, talking points |
| Minutes and decisions | Decisions, owners, dates, approval, carry-forward commitments, links back to evidence |
| Collaboration | Shared workspaces, conversations, comments, mentions, assignments, review and sign-off |
| Data | Conversational file upload, mapping, data-quality checks, semantic definitions, governed and uploaded source labels |
| Integrations | Microsoft Teams and Outlook first; email and Slack where relevant; managed data connectors |
| Feedback and learning | Structured downvote reasons, corrections, review queue, regression tests, approved reusable answers |
| Advanced analysis | Driver analysis, contribution, rate-volume-mix, target gaps, controlled scenarios and transparent forecasts |
| Enterprise readiness | SSO, MFA, tenants, roles, row/column security, audit, retention, isolation, administration |
| Commercialization | Analyst, QBR Pro and Enterprise editions; focused pilot; measurable success criteria |
| Deprioritized ideas | Avatars, personality features, unrestricted agents, generic web search and novelty voice experiences |

## Product north star

Every useful answer should support four steps:

1. **Understand** — state the finding in plain business language.
2. **Verify** — show the scope, measure, calculation, freshness, and evidence.
3. **Act** — turn the finding into a slide, decision, action, or export.
4. **Monitor** — follow the metric and notify the owner when it materially changes.

The desired flow is:

`Ask -> verify -> explore -> add to QBR -> decide -> assign -> monitor -> recap`

## Product-wide design principles

1. **Show business measures, not model scores.** Currency, percentages, ranks, survey scores, and dates are explainable. A synthetic score is not explainable unless its formula and inputs are visible and approved.
2. **Every comparison must name its basis.** Use labels such as `QoQ`, `Q2 2026 vs Q1 2026`, `YTD vs prior YTD`, or `vs peer average`; never use an unspecified change.
3. **Every classification must show its trigger.** A risk can be called high only when the user can see the threshold that was crossed.
4. **Preserve scope everywhere.** Carrier, country, product line, industry, period, currency, and peer group should remain visible as context chips.
5. **Separate facts from recommendations.** The calculated evidence should be visually distinct from AI-written interpretation and recommended action.
6. **Use AI for language and prioritization, not for inventing measures.** Calculations, thresholds, filters, and comparisons should be deterministic.
7. **The screen and PowerPoint must agree.** A widget must use the same labels, values, filters, and definitions in the app and in exported slides.

## Validation of the proposed Boardroom changes

| Current widget | Verdict | Reason |
| --- | --- | --- |
| Risks & watch items | **Replace the presentation model** | `High`, `Med`, and `Low` currently have no visible calculation or threshold. A business user cannot defend the classification. |
| Opportunity radar | **Replace** | A normalized `0-100` gap score hides the monetary size and business context of the opportunity. |
| Insight timeline | **Change to quarterly performance by default** | QBR users need movement between adjacent quarters. A timeline containing only annual points does not help them run a quarterly conversation. |
| Market opportunity map | **Replace** | The country-by-product intensity grid combines several ideas into one unexplained score. Ranked industry whitespace expressed in premium is more actionable. |
| Positioning matrix | **Also simplify** | Its current normalized `0-100` premium-strength and perception axes have the same explainability problem as the opportunity radar. Use actual premium/share of wallet and actual broker score. |

### Important qualification on QoQ

Quarter-on-quarter should be the default only when the source contains complete and comparable quarters. The widget should not manufacture quarterly values from annual survey data or compare an incomplete quarter with a complete one.

When quarterly data is unavailable:

- hide the widget and explain that quarterly history is unavailable;
- use `YTD vs prior YTD` when both periods cover the same months or quarters; or
- show an annual trend only when the question is explicitly strategic or multi-year.

## 1. Risks and watch items -> Evidence-backed watchlist

### Problem

The current card shows a risk name, a severity word, and a colored progress bar. The bar width is a visual mapping of the severity label rather than a business quantity. The audience cannot answer:

- What created this risk?
- How much premium is exposed?
- Which threshold was crossed?
- What period is being compared?
- What action is expected?

### Recommended replacement

Rename the widget **Risk & Watchlist** and show one row per issue.

Each row should contain:

| Field | Example |
| --- | --- |
| Risk | Property premium contraction |
| Scope | Canada / Property / Chubb |
| Premium exposed | £12.4m |
| Current movement | -14.2% QoQ |
| Comparison | Q2 2026 vs Q1 2026 |
| Trigger | Breached approved -10% QoQ threshold |
| Duration | Declined for 2 consecutive quarters |
| Priority | High — threshold exceeded on material premium |
| Owner/action | Review top-lost industries with Placement team |

### How priority should be calculated

Do not let the language model choose `High`, `Med`, or `Low` freely. Priority must come from approved rules that are visible from the card.

A recommended rule structure is:

1. **Materiality:** Is the premium, client segment, or market large enough to matter?
2. **Magnitude:** How far has the measure moved beyond the approved threshold?
3. **Persistence:** Is it a one-quarter movement or a repeated trend?
4. **Business breach:** Has rank, broker score, share of wallet, or another governed KPI crossed a target?
5. **Data confidence:** Are the periods complete and comparable?

Suggested classification behavior:

- **High:** material premium plus a severe threshold breach, or two or more material adverse signals.
- **Medium:** one material adverse signal or a repeated early-warning movement.
- **Low:** below materiality, a single weak signal, or a movement that has not yet crossed the approved threshold.

The numeric thresholds must be configurable by the business. Until those thresholds are approved, show the raw facts and omit the priority label.

> **Status (2026-09-08).** The thresholds were never signed off, so under the rule above the label had to go — and it has. The rule engine (`core/boardroom/priority.py`) and its `thresholds.yaml` are deleted rather than left running to produce a label nothing prints. The watchlist now shows the premium exposed where the severity pill sat and is ordered by it, on screen and on the slide. Reinstating a priority means restoring that module behind approved numbers, not re-adding a label to the card.

### Interaction

- Hover or click `Why High?` to see the exact rule and inputs.
- Select an item to open the supporting industries, products, quarters, and data rows.
- Allow `Create action`, `Assign owner`, `Set review date`, and `Watch this risk`.
- Sort by premium exposed first, then magnitude and persistence.

## 2. Opportunity radar -> Product line headroom

### Problem

Numbers such as `70` or `80` are normalized opportunity scores. They do not tell a relationship leader whether an opportunity is worth £100k or £20m, and their meaning changes depending on how the score is normalized.

### Recommended replacement

Rename the widget **Product Line Headroom** and use a ranked horizontal bar or compact table.

Display:

| Product line | Carrier premium | Marsh premium | Share of wallet | Whitespace premium | Market QoQ | Suggested focus |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Property | £8.2m | £42.0m | 19.5% | £33.8m | +6.4% | Expand in Manufacturing |
| Cyber | £0.4m | £11.7m | 3.4% | £11.3m | +18.1% | Validate appetite |

Primary sort: **Whitespace premium**, descending.

If carrier premium is part of Marsh premium, calculate:

`Whitespace premium = max(Marsh premium - carrier premium, 0)`

If the datasets use another definition, the product must show that approved definition rather than silently using this formula.

### Visual treatment

- Use a paired bar: total Marsh premium as the full bar and carrier premium as the filled portion.
- Print both currency values directly on the bar.
- Show share of wallet as supporting context, not as the only measure.
- Mark zero-premium rows with `No current premium`, not `100 opportunity`.
- Keep any composite priority score behind an optional methodology drawer, never as the headline value.

## 3. Insight timeline -> Quarterly performance

### Problem

A year-over-year event timeline is too coarse for a QBR. It can also mix premium, rank, and survey movements that occur at incompatible reporting frequencies.

### Recommended replacement

Rename the widget **Quarterly Performance**.

For each comparable quarter, show:

- quarter label;
- actual premium;
- QoQ premium change in currency and percentage;
- share of wallet;
- rank change when available;
- the main product or industry driver; and
- a data-completeness indicator.

Example:

| Quarter | Premium | QoQ change | Share of wallet | Main driver |
| --- | ---: | ---: | ---: | --- |
| Q4 2025 | £20.1m | — | 12.8% | Baseline |
| Q1 2026 | £22.4m | +£2.3m / +11.4% | 13.5% | Property growth |
| Q2 2026 | £19.2m | -£3.2m / -14.3% | 11.9% | Construction decline |

### Rules

- Compare adjacent, complete quarters only.
- Use a maximum of the latest 6-8 quarters.
- Do not combine annual survey scores with quarterly premium on a single line.
- If survey data is annual, show it as a separately labeled annual marker or separate widget.
- Provide an optional `QoQ / YTD / Annual` switch only when all selected views are valid.
- Default to the quarter relevant to the user's question or current QBR scope.

## 4. Market opportunity map -> Industry whitespace

### Problem

The existing heatmap maps products and markets to an intensity from `0-100`. It does not show how much premium Marsh writes, how much the carrier receives, or why a cell is an opportunity.

### Recommended replacement

Rename the widget **Industry Whitespace** or **Marsh Book Whitespace**.

Show industries where Marsh has meaningful premium but the selected carrier has zero or low premium.

Recommended columns:

| Industry | Marsh premium | Carrier premium | Carrier share of wallet | Whitespace premium | Marsh QoQ | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Manufacturing | £18.6m | £0.0m | 0.0% | £18.6m | +8.2% | No current premium |
| Construction | £15.2m | £0.9m | 5.9% | £14.3m | +3.1% | Low presence |

### Required filters

- **Product line** — required and visible; defaults to the product in the user's question.
- Country/market.
- Quarter or period.
- Carrier.
- Minimum Marsh premium.
- `No premium only` / `Low premium` / `All whitespace`.
- Top N industries.
- Optional minimum market growth.

### Whitespace rules

An industry should qualify only when:

1. Marsh premium is above an approved materiality threshold; and
2. carrier premium is zero or below an approved low-presence threshold.

The current analytics concept already follows the right foundation: it defines whitespace as carrier premium near zero while Marsh/market premium is materially present. The improved widget should expose those actual premium values and extend the definition from only zero premium to a configurable low-presence rule.

Possible low-presence definitions include:

- carrier premium below an absolute threshold;
- carrier share of wallet below a configured percentage; or
- carrier share of wallet materially below its portfolio or peer benchmark.

The business must select one canonical definition. The UI should display it through a `How whitespace is calculated` link.

### Recommended chart

Use a ranked horizontal paired bar rather than a geographic-style heatmap:

- full bar = Marsh premium in the industry;
- filled portion = carrier premium;
- remaining portion = whitespace premium;
- label = currency amount plus share of wallet;
- color = presence state, not an unexplained opportunity score.

The table view should remain available for sorting and export.

## 5. Positioning matrix -> Actual-measure positioning

Although not part of the original request, this widget has the same explainability risk.

Replace normalized axes with:

- x-axis: actual carrier premium or share of wallet;
- y-axis: actual broker survey score;
- vertical benchmark: peer-average share of wallet or agreed target;
- horizontal benchmark: peer-average broker score;
- labels that show the actual values on hover and in PowerPoint notes.

Do not transform the values to `0-100` merely to fit the chart. Axis formatting should adapt to the real units.

## 6. Boardroom filters and scope

### Global context bar

Keep the active scope visible at the top of the Boardroom:

`Carrier: Chubb | Country: Canada | Product: Property | Period: Q2 2026 | Currency: GBP | Peers: Custom set`

Changing a global filter should refresh every compatible widget and regenerate only the affected interpretation.

### Widget-level filters

Use widget filters only when the widget needs a narrower cut than the global scope. Industry Whitespace requires a product-line filter because its purpose is to rank industries within a product.

### Filter integrity

- Filtering must be applied to deterministic analytics, not to already-written model text.
- The filtered scope must appear in the widget title and export.
- A filter that produces insufficient data should result in a clear empty state.
- The user should be able to reset a widget to the Boardroom's global scope.

## 7. Trust layer for every chatbot and Boardroom answer

Add an expandable **How this was calculated** panel containing:

- interpreted question;
- active filters and exclusions;
- metric definition;
- formula;
- current and comparison periods;
- data source and last refresh;
- evidence rows or chart;
- verification status;
- data-quality or comparability warnings.

Use answer states such as:

- `Verified`;
- `Verified with incomplete period`;
- `Partially supported`;
- `Insufficient comparable data`; and
- `Unable to verify`.

This is more useful than a generic disclaimer that AI can make mistakes.

### Verified-answer library

Allow authorized business owners to approve canonical answers for sensitive, nuanced, or frequently asked questions. A verified answer should store:

- trigger phrases and business synonyms;
- the approved metric and calculation;
- required filters and exclusions;
- the approved visual or table;
- owner, review date, and version; and
- the conditions under which the answer must not be used.

When a question matches, the assistant should prefer this approved path and label the result `Verified answer`. The model may explain the result but should not change the approved calculation.

## 8. Answer-to-action toolbar

Every suitable chatbot answer should offer contextual actions:

- Explore drivers.
- View evidence.
- Add to QBR.
- Create or replace a slide.
- Pin to Boardroom.
- Create a decision.
- Create and assign an action.
- Export data.
- Share a verified link.
- Watch this metric.

Pitch Builder and Boardroom Mode should remain available in the composer menu, but the relevant action should also appear directly below an answer. Users should not need to know which workspace owns the next step.

## 8A. Chatbot productivity and personalization

### Command shortcuts

Offer task-oriented starting actions in addition to an empty prompt:

- `Brief me` — summarize the selected account or market.
- `Compare` — select subjects, measure, and period.
- `Explain change` — run driver and contribution analysis.
- `Find whitespace` — open product and industry opportunity analysis.
- `Build a slide` — convert the current finding into an editable slide.
- `Prepare my meeting` — assemble recap, questions, risks, decisions, and open actions.
- `Track this` — create a watch with an explicit condition.

These commands should remain natural-language shortcuts, not rigid separate assistants.

### Account and workspace memory

Remember durable, user-approved context such as:

- preferred carrier and country scope;
- default product lines;
- custom peer set;
- reporting currency and conversion policy;
- fiscal calendar;
- approved materiality thresholds;
- preferred QBR template and audience;
- frequently used analyses; and
- open decisions and recurring commitments.

Show remembered context and allow users to edit, temporarily override, or forget it. Do not silently treat conversational guesses as permanent business facts.

### Guided failure recovery

When the assistant cannot answer, it should explain the specific blocker and provide the next valid action. Examples:

- `Quarterly history is unavailable; use annual trend instead.`
- `Product line is missing from this dataset; map a column or choose another source.`
- `The selected peer group has insufficient members for a confidential benchmark.`
- `Q2 is incomplete; compare Q1 or use like-for-like YTD.`
- `This calculation is not yet approved; view the raw data or request verification.`

A generic error should be the final fallback, not the normal recovery experience.

## 9. Proactive analyst experience

### Watchlists

Allow users to follow a carrier, country, product line, industry, decision, or KPI.

Notify only when:

- an approved threshold is crossed;
- a material new whitespace appears;
- a risk persists for another quarter;
- data is refreshed and changes a previously shared conclusion;
- a decision or action is overdue; or
- a QBR is approaching and required inputs are missing.

### Briefings

Offer daily, weekly, monthly, and pre-QBR briefings. Each briefing should contain only the top material changes, with direct links to evidence and actions.

### Delivery channels

Prioritize Microsoft Teams and Outlook for the likely enterprise workflow. Slack and email can follow where relevant.

## 9A. Portfolio command centre

Create a role-aware homepage that answers `What needs my attention?` before the user asks a question.

Recommended modules:

- watched carriers and product lines;
- material premium movements since the last refresh;
- new or expanding industry whitespace;
- risks whose approved thresholds were crossed;
- upcoming QBRs and missing preparation inputs;
- decisions awaiting approval;
- overdue actions and unresolved prior-quarter commitments;
- stale or failed data refreshes; and
- recently approved Boardrooms and recaps.

Every module should open the governed analysis behind it and offer the relevant next action. The page should be personalized by role: executives see exceptions and decisions, relationship leaders see accounts and opportunities, and analysts see data issues and work queues.

## 10. Collaboration and execution

Add:

- shared conversations and Boardrooms;
- comments and mentions;
- assigned owners and due dates;
- approval and sign-off;
- decision and slide revision history;
- links between an answer, slide, decision, meeting minute, and follow-up action;
- a visible record of who approved a client-facing output; and
- a quarterly carry-forward of unresolved commitments.

The Decision Board should be the execution layer, not a separate place where users manually retype the conclusion from chat.

## 11. Conversational data and file analysis

Allow a user to attach Excel, CSV, PowerPoint, PDF, prior QBR, or meeting notes directly in chat.

The assistant should:

1. inspect the file;
2. describe what it found;
3. propose column and metric mappings;
4. identify missing or poor-quality fields;
5. ask for approval where mappings are ambiguous;
6. retain the approved semantic mapping for that workspace; and
7. answer using the same governed analytics engine as the standard data sources.

Uploaded data must be clearly labeled so users can distinguish it from governed warehouse data.

## 12. Better feedback and learning

A thumbs-down should ask what failed:

- wrong scope;
- wrong metric;
- wrong period;
- incorrect or missing evidence;
- confusing explanation;
- unsuitable chart;
- missing business context; or
- other, with a written correction.

The correction should create a review item and, once approved, contribute to:

- verified answers;
- terminology mappings;
- regression tests;
- chart selection rules; and
- future answer suggestions.

Do not silently learn factual business rules from an unreviewed downvote.

## 13. Enterprise readiness

Before broad external production use, add:

- SSO and MFA through the customer's identity provider;
- organizations, workspaces, users, and groups;
- role-based feature permissions;
- row- and column-level data security;
- dataset-level access controls;
- audit logs for prompts, answers, exports, approvals, and administrative changes;
- retention and deletion policies;
- environment and tenant isolation;
- encryption and secrets management;
- usage, latency, quality, and cost administration; and
- controlled model/provider configuration.

The existing username-only local sign-in is suitable for development and a controlled demo, not an enterprise deployment.

## 14. Completing the Recap experience

The Recap workspace should become an executive briefing generator using the same evidence as chat and Studio.

Outputs:

- one-page executive recap;
- three numbers that matter;
- what changed this quarter;
- top risks and top whitespace in actual premium;
- decisions required;
- unresolved actions from the previous review;
- suggested talking points; and
- links to the source Boardroom widgets.

The recap should be editable, verifiable, exportable, and shareable.

## 15. Driver and scenario analysis

Later-stage additions:

- contribution analysis explaining which product, country, or industry drove a movement;
- rate-volume-mix where the required inputs exist;
- scenario comparisons with user-controlled assumptions;
- target-setting and gap-to-target analysis;
- forecast ranges with transparent assumptions and uncertainty; and
- recommended actions linked only to evidence-supported drivers.

Do not launch forecasting as an unexplained single number. Scenarios should be clearly separated from observed facts.

## 15A. Ideas to defer

Do not prioritize the following until the governed answer-to-action workflow is strong:

- avatars or animated assistant characters;
- personality customization as a headline feature;
- novelty voice conversations without a meeting workflow;
- unrestricted autonomous agents;
- generic web search disconnected from governed insurance data;
- synthetic scores created primarily to make widgets look sophisticated; and
- a large marketplace of loosely governed tools.

These may improve demos, but they do not resolve the buyer's core questions: `Can I trust the number?`, `Does it remove meaningful work?`, and `Can my team act on it safely?`

## 16. Sellable product package

### Sell the workflow, not the chat

The core promise should be:

> Produce and run a governed QBR in under 30 minutes, then track every resulting decision.

The differentiator is one governed calculation flowing through:

`Answer -> chart -> slide -> decision -> minutes -> follow-up`

### Suggested editions

**Analyst**

- governed chat;
- explainable charts and data tables;
- evidence panel;
- Excel export; and
- saved conversations.

**QBR Pro**

- everything in Analyst;
- QBR Studio;
- Boardroom;
- Recap;
- PowerPoint export;
- Minutes of Meeting;
- decisions and actions; and
- watchlists and briefings.

**Enterprise**

- everything in QBR Pro;
- SSO, roles, row-level security, and audit;
- shared workspaces and approvals;
- Teams/Outlook integration;
- custom data connectors and semantic definitions;
- private or customer-controlled deployment options; and
- administrative quality and usage reporting.

### Pilot structure

Use one market, one carrier, one customer PowerPoint template, and a small group of real users. Demonstrate the full flow from data to verified answer, slide, decision, minutes, and follow-up.

Suggested pilot measures:

- QBR preparation time;
- percentage of figures with valid evidence;
- pages accepted without major edits;
- number and cause of user corrections;
- zero unauthorized peer disclosure;
- weekly returning users;
- action completion rate; and
- time from data refresh to an approved executive brief.

Targets should be agreed with the pilot sponsor rather than presented as universal benchmarks.

## 17. Recommended delivery sequence

### Phase 1 — Explainable Boardroom

1. Replace Risks & Watch Items with the evidence-backed watchlist.
2. Replace Opportunity Radar with Product Line Headroom.
3. Replace Market Opportunity Map with Industry Whitespace.
4. Change the timeline to comparable quarterly performance.
5. Replace normalized positioning axes with actual measures.
6. Add global scope chips and the Industry Whitespace product-line filter.
7. Keep app and PowerPoint output semantically identical.

### Phase 2 — Trust and action

1. Add the calculation/evidence panel.
2. Add answer-to-action controls.
3. Connect chat conclusions directly to slides, decisions, and actions.
4. Introduce structured feedback reasons and approved verified answers.

### Phase 3 — Repeat use

1. Complete Recap.
2. Add watchlists and material-change alerts.
3. Add periodic and pre-QBR briefings.
4. Add Teams and Outlook delivery.

### Phase 4 — Enterprise deployment

1. Add SSO, tenants, roles, and row-level security.
2. Add collaboration, approval, and audit capabilities.
3. Add managed connectors, data refresh, and administrative controls.
4. Package the product editions and launch a measured pilot.

## 18. Boardroom acceptance criteria

A revised Boardroom is ready when:

- no primary widget displays an unexplained normalized score;
- every risk shows the affected business scope, premium exposure, comparison period, and trigger;
- every priority label can explain exactly why it was assigned;
- every opportunity shows Marsh premium and carrier premium in currency;
- Industry Whitespace can be filtered by product line;
- low presence and zero presence use an approved, visible definition;
- quarterly timelines compare complete adjacent quarters;
- missing or non-comparable periods produce an honest empty state;
- every widget can open its evidence and metric definition;
- the selected scope is visible in the widget and exported slide;
- PowerPoint shows the same values and definitions as the app; and
- a user can create a slide, decision, action, or watch directly from the finding.

## 19. Open business decisions

These decisions require domain-owner approval before implementation:

1. Is `Marsh premium` defined as all premium in the Marsh book after the selected filters?
2. Is carrier premium always a subset of Marsh premium for the proposed whitespace formula?
3. What makes market premium materially present?
4. What is the approved definition of low carrier presence: currency, share of wallet, benchmark gap, or a combination?
5. Which thresholds create high, medium, and low priority for each metric?
6. Are quarters calendar-based or market-specific fiscal quarters?
7. How should incomplete quarters be labeled and compared?
8. What is the default currency and conversion-date policy?
9. Should survey movements appear only annually or as separate dated markers?
10. Which roles may approve thresholds, verified answers, and client-facing exports?

## Market validation

The direction is consistent with current enterprise analytics expectations:

- Power BI Copilot provides citations, verified answers, semantic-model preparation, and access-aware responses: <https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-apps-overview>
- Microsoft recommends AI data schemas, verified answers, business instructions, and model descriptions for reliable natural-language analytics: <https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai-faq>
- Tableau Pulse supports followed metrics and scheduled insight digests through email, Slack, and Microsoft Teams: <https://help.tableau.com/current/online/en-us/pulse_explore_metrics.htm>
- Tableau Agent applies existing row- and column-level security to the data available to the assistant: <https://help.tableau.com/current/online/en-us/web_author_einstein.htm>

These products validate citations, governed definitions, proactive delivery, and security as table stakes. Virtual Analyst can differentiate by connecting those expectations to the complete insurance QBR workflow.

## Validation evidence and limitation

The current Boardroom product definitions confirm the explainability concern:

- Risk severity is a free-form `High`, `Med`, or `Low` field and is rendered as a fixed-width visual severity bar.
- Opportunity Radar explicitly requests a normalized `0-100` gap score.
- Market Opportunity Map explicitly requests a normalized `0-100` intensity.
- The timeline permits a year or a year-quarter and is activated whenever two distinct period values are detected, without requiring quarterly grain.
- The positioning matrix normalizes both premium strength and broker perception to `0-100`.

The current whitespace analytics foundation is stronger than the widget presentation: it already calculates Marsh/market premium with the carrier filter removed and identifies slices where carrier premium is near zero while market premium is present. The recommended redesign exposes those actual measures rather than asking the presentation model to convert them into an abstract score.

A live Boardroom generation was attempted during this validation, but the answer returned a generic error. Therefore this document is a product and semantic validation grounded in the current schemas, analytics definitions, and rendering behavior; it is not presented as a completed end-to-end visual audit.
