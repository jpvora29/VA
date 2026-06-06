# Flow Registry Design

## Goal

Make each data family discoverable through metadata instead of scattered code.
Adding a dataset should mean adding one registry entry plus skills/tests, not
editing routing prompts, SQL helpers, chart logic, Pitch Builder filters, and
report prompts independently.

## Registry Shape

Proposed file: `core/registry/flows.yaml` or `core/registry/flows.py`.

```yaml
survey:
  label: Survey
  route_label: survey
  pitch_eligible: true
  tables:
    primary: Carriers
    supporting: [Peers]
  allowed_tables: [Carriers, Peers]
  date_columns:
    year: Survey_Year
  entity_columns:
    country: SurveyCountry
    carrier: Carrier
    product: SurveyPractice
  metrics:
    score:
      columns: [Score]
      default_aggregation: AVG
      aliases: [score, broker score, perception, satisfaction]
    nps:
      columns: [NPS Score]
      default_aggregation: AVG
      aliases: [nps, net promoter score]
  valid_values_source:
    type: python
    object: core.data.valid_values.GetValidData.valid_values
  definitions_source:
    type: python
    object: core.data.valid_values.GetValidData.definitions
  chart_defaults:
    measure_priority: [Score, NPS Score]
    dimension_priority: [SurveyPractice, Section, Attribute, SurveySegment, SurveyCountry]
  confidentiality:
    peer_names_allowed: false
```

```yaml
gpr:
  label: Premium
  route_label: premium
  pitch_eligible: true
  tables:
    primary: GPR
    supporting: [Peers]
  allowed_tables: [GPR, Peers]
  date_columns:
    date: Billing_Date
    year: Year
    month: Month_Name
  entity_columns:
    country: Country
    carrier: Carrier_Group
    product: Product_Line
    segment: Client_Segment
  metrics:
    premium:
      columns: [Premium]
      default_aggregation: SUM
      aliases: [premium, gross premium, revenue, book]
    share_of_wallet:
      columns: [Premium]
      derived: true
      aliases: [sow, share of wallet, wallet share, share in marsh book]
    share_of_portfolio:
      columns: [Premium]
      derived: true
      aliases: [appetite, share of portfolio, portfolio share, product mix]
  valid_values_source:
    type: python
    object: core.data.valid_values.GetValidData.valid_values_gpr
  definitions_source:
    type: python
    object: core.data.valid_values.GetValidData.definitions_gpr
  chart_defaults:
    measure_priority: [Premium, SoW, Appetite, YoY Growth]
    dimension_priority: [Product_Line, Business_Line, Client_Segment, Country, Carrier_Group]
  confidentiality:
    peer_names_allowed: false
```

## Interfaces

The registry should expose these read-only helpers:

```python
flow = flow_registry.get("gpr")
flow.allowed_tables
flow.schema(engine)
flow.valid_values()
flow.definitions()
flow.metric("share_of_wallet")
flow.resolve_alias("gross premium")
flow.pitch_filter_columns()
```

## Replacement Targets

Move these behaviors behind the registry:

- `core.mcp.tools._SCHEMA_TABLES_BY_FLOW`
- `core.mcp.tools.get_valid_values()`
- `core.mcp.tools.get_definitions()`
- `GeneralFunctions.get_database_schema()` fixed table assumptions
- routing table-family labels and aliases
- Pitch Builder option queries and filter columns
- chart dimension/measure priority lists
- metric synonym rules in prompts

## New Dataset Extension Process

1. Add table(s) to SQLite or a connected warehouse.
2. Add a registry entry with tables, entity columns, metrics, aliases, and
   pitch eligibility.
3. Add skills under `codex changes/skills/<flow>/`.
4. Add golden tests for routing, SQL, response, charting, and pitch inclusion.
5. Run a coverage report that confirms every metric has definitions, examples,
   and validation tests.

