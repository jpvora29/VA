"""Few-shot calibration examples embedded in both tagging prompts.

Drawn from real QBR deck content (AIG/Talbot, Allianz Specialty, Swiss Re NL, Zurich
UK, Chubb HK, Great Eastern SG): 2-3 examples per sub-tag, covering all ten scored
sub-tags in ``data/tag_list.csv``. Add a sub-tag there and it belongs here too.
"""
FEW_SHOT_EXAMPLES = (
    "Examples (do not tag these -- use them as calibration only):\n\n"

    # ── Strategic Priorities & Focus Areas (3 examples) ───────────────────────────
    "[ex_01] AIG's priority focus areas for 2026 include Data Centres, Cyber relaunch, Everest Business renewals, "
    "and maximising GPW from facilities, QS, and line slips.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "Strategic Priorities & Focus Areas"}\n'
    "Reason: Explicit carrier-stated H1/H2 priority lines and named strategic growth segments for the period.\n\n"

    "[ex_02] Zurich's strategic focus areas for 2026: Major Customers (P&C), Specialty LoBs, pipeline management, "
    "Mid Market, and facilities across RM, Corporate and Commercial.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "Strategic Priorities & Focus Areas"}\n'
    "Reason: Named strategic pillars and target customer segments defining the carrier's engagement priorities with Marsh.\n\n"

    "[ex_03] Marsh Specialty UK priorities 2026: cutting the tail initiative to optimise trading, driving digital "
    "transformation, and rollout of Whitespace and Broker Workbench platforms across new business and renewals.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "Strategic Priorities & Focus Areas"}\n'
    "Reason: Marsh-side strategic priorities covering placement efficiency, digital rollout, and client outcome improvement.\n\n"

    # ── New Initiatives & Partnerships (3 examples) ────────────────────────────────
    "[ex_04] Talbot launched an expanded Portfolio Solutions offering ahead of 2026 YOA, targeting six facility "
    "types including Marine Slipstream, Cyber Echo, Specie QS, Marsh Alpha, and FINPRO QS.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "New Initiatives & Partnerships"}\n'
    "Reason: Named new facility launches and joint programme arrangements between carrier and Marsh.\n\n"

    "[ex_05] Marsh established a new London team dedicated to servicing McGriff and MMA wholesale business, "
    "as part of the One Marsh approach to reduce wholesale leakage.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "New Initiatives & Partnerships"}\n'
    "Reason: New dedicated Marsh team formation to service a named wholesale business partner -- a structural partnership initiative.\n\n"

    "[ex_06] Zurich successfully secured a line on Marsh's Cargo LATAM facility and participates across "
    "12 facilities with Marsh, with a clear ambition to expand the facility footprint further.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "New Initiatives & Partnerships"}\n'
    "Reason: Named facility participation and expansion ambition -- a concrete joint programme and partnership development item.\n\n"

    # ── Digital & Innovation (2 examples) ─────────────────────────────────────────
    "[ex_07] AIG is investing in AI through Underwriter Assist and Claims Assist tools, and is aligning with "
    "Marsh's Digital Infrastructure Strategy for data centres in the US.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "Digital & Innovation"}\n'
    "Reason: Explicit AI tooling investment and digital strategy alignment -- technology innovation at the carrier level.\n\n"

    "[ex_08] Rollout of Broker Workbench (BWB) platform across Business Units for new business, renewals, "
    "and portfolio solutions; accelerating digital transformation to enhance efficiency and client outcomes.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "Digital & Innovation"}\n'
    "Reason: Named digital platform rollout (BWB) spanning the full placement lifecycle -- a core digital initiative.\n\n"

    # ── Carrier Service Quality & Survey Feedback (3 examples) ────────────────────
    "[ex_09] Great Eastern 2024 Carrier Survey feedback: poor service delivery, delayed response times, "
    "poor renewal onboarding experience impacting clients, and lack of client-centric mindset.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "Carrier Service Quality & Survey Feedback"}\n'
    "Reason: Direct broker observations from a named carrier performance survey -- qualitative service quality signals.\n\n"

    "[ex_10] AIG Leading Edge feedback for Cyber Retail: effective primary lead capabilities, long-standing "
    "relationship. Cyber Wholesale: harder to trade with than peers, clarity on appetite needed, "
    "LE rank 26 (down 7 YoY).\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "Carrier Service Quality & Survey Feedback"}\n'
    "Reason: Named Leading Edge survey results per product line with highlighted strengths and gaps -- service quality assessment.\n\n"

    "[ex_11] Swiss Re Corporate Solutions Underwriting score tracked YoY by Practice (Casualty, FINPRO, "
    "Property, Marine, Cyber). Claims Professionals score compared vs peer group across six practices.\n"
    '-> {"umbrella_tag": "Strategy & Initiatives", "sub_tag": "Carrier Service Quality & Survey Feedback"}\n'
    "Reason: Structured carrier performance survey scores across underwriting and claims dimensions -- the Marsh survey framework.\n\n"

    # ── What's Working Well (3 examples) ──────────────────────────────────────────
    "[ex_12] Talbot's International Property book with Marsh grew 70%, significantly outpacing Marsh's "
    "overall growth. North American Property also grew +27.75%, with share of book improving.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "What\'s Working Well"}\n'
    "Reason: Named product lines with quantified outperformance against Marsh portfolio growth -- positive performance data by LoB.\n\n"

    "[ex_13] Allianz Natural Resources GWP grew +23.6% YoY globally; UK SoW moved from 3.3% to 4.0%; "
    "Singapore ranked #1 with SoW of 14.8%. Strong relationships and responsiveness noted in LAC.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "What\'s Working Well"}\n'
    "Reason: Named product line with outperforming regions, quantified SoW gains, and rank improvements.\n\n"

    "[ex_14] Zurich ranked #1 in RM P&C. Holds 5th position in Energy with YoY GWP growth in Power (+11.2%). "
    "Ranked 1st in Financial Institutions and 2nd in Specie within FINPRO.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "What\'s Working Well"}\n'
    "Reason: Multiple product lines where carrier holds top rank positions with quantified growth data -- outperformance by LoB.\n\n"

    # ── What's Not Working / Challenges (3 examples) ──────────────────────────────
    "[ex_15] Talbot Marine Hull ranked 30th (down 7 vs prior year), below-average Leading Edge score. "
    "Personnel challenges and depth of expertise issues impacting service quality.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "What\'s Not Working / Challenges"}\n'
    "Reason: Named product line with rank deterioration, below-average LE score, and identified service issues -- a challenge area.\n\n"

    "[ex_16] Swiss Re Netherlands Construction GWP declined -60.1% YoY. Management Liability down -57.4%. "
    "Total book declined -12.1% while Marsh portfolio fell only -25.9%.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "What\'s Not Working / Challenges"}\n'
    "Reason: Named product lines in a specific country with significant GWP contractions -- concrete underperformance data.\n\n"

    "[ex_17] Allianz has no Aviation underwriting capacity in Denmark, Sweden, Belgium, or Netherlands. "
    "In Asia Pacific, no local underwriting in Singapore, Hong Kong, Korea, or Australia.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "What\'s Not Working / Challenges"}\n'
    "Reason: Identified capacity gaps by country -- structural barriers preventing carrier from trading in named local markets.\n\n"

    # ── Growth Opportunities & Pipeline (3 examples) ───────────────────────────────
    "[ex_18] Allianz H1 2026 pipeline: Knorr Bremse Cyber (Germany), Theo Mueller Cyber, Atlas Copco "
    "Liability and Financial Lines (Sweden), Klarna Casualty and Marine Cargo.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "Growth Opportunities & Pipeline"}\n'
    "Reason: Named pipeline accounts with specific lines of business, countries, and inception dates -- active growth pipeline entries.\n\n"

    "[ex_19] Great Eastern upcoming opportunities: Savills Singapore, Quess Corp, Cardinal Health, "
    "Keppel Group, and CIMB -- Corporate and GBM segments with July 2025 to January 2026 inceptions.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "Growth Opportunities & Pipeline"}\n'
    "Reason: Named client pipeline with product, segment, and inception date -- a forward-looking opportunity register by country.\n\n"

    "[ex_20] Allianz aims to be recognised as a lead market in specialty; requested deep-dive workshops "
    "with Marsh to explore growth in D&O cross-sell and targeted smart pipeline on specific accounts.\n"
    '-> {"umbrella_tag": "Country / Product / Region", "sub_tag": "Growth Opportunities & Pipeline"}\n'
    "Reason: Strategic pipeline development intent with named cross-sell focus and workshop engagement to convert opportunities.\n\n"

    # ── KPIs & Performance Headlines (3 examples) ─────────────────────────────────
    "[ex_21] Allianz Commercial global GWP with Marsh: $2.0bn, +4.2% YoY. SoW 2.7%, up 1pp YoY. "
    "Ranked 8th globally, up 1 place. North America GWP $1.0bn, +7.7% YoY.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "KPIs & Performance Headlines"}\n'
    "Reason: Headline GWP totals, YoY growth, SoW percentage, and rank -- the numerical performance backbone of the QBR.\n\n"

    "[ex_22] Swiss Re Netherlands total GWP EUR 11.5m, -12.1% YoY. New business GWP EUR 5.29m, +25.5% YoY. "
    "Property new business up +339.6% with SoW 13.3%, ranked 3rd.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "KPIs & Performance Headlines"}\n'
    "Reason: Country-level GWP totals, YoY change, new business volume, SoW, and rank -- core KPI reporting for the period.\n\n"

    "[ex_23] Great Eastern share of wallet within MMB portfolio grew from 16% in 2021 to 20% in 2024. "
    "Overall MMB portfolio grew 95% from $49m in 2021. GE contributed $26m in new clients in 2024.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "KPIs & Performance Headlines"}\n'
    "Reason: Multi-year SoW trajectory, portfolio growth %, and new client GWP -- performance headline metrics over the review period.\n\n"

    # ── Outperformers & Underperformers (3 examples) ───────────────────────────────
    "[ex_24] AIG Crisis Management (up 95.4%) and Cyber (up 39.5%) are outperforming pace of growth in "
    "the Marsh portfolio. AIG also growing faster than Marsh in FI, Energy, PEMA, and RM P&C.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "Outperformers & Underperformers"}\n'
    "Reason: Named lines beating the Marsh portfolio benchmark with specific YoY percentages -- narrative layer around KPI numbers.\n\n"

    "[ex_25] Talbot D&O down 45.6% YoY due to challenging rating environment. Marine Cargo declined 19.7% "
    "YTD. Product Recall growing more slowly than the overall Marsh portfolio.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "Outperformers & Underperformers"}\n'
    "Reason: Named product lines with specific underperformance percentages and attributed causes -- contrast to KPI headlines.\n\n"

    "[ex_26] AIG ranked #2 overall across Marsh book and #1 in Energy, Marine, and PEMA. "
    "In Renewables, rank dropped from 2nd to 4th; not growing in line with Marsh portfolio.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "Outperformers & Underperformers"}\n'
    "Reason: Mixed rank story -- top-line strength in key lines offset by rank deterioration in a specific product.\n\n"

    # ── Rate & Pricing & Market Conditions (3 examples) ────────────────────────────
    "[ex_27] Q1 2026 Global Insurance Market Index: commercial insurance rates decreased 5%, vs a 6% decrease "
    "in Q4 2025. Casualty, Financial Lines, Cyber, and Property all showing rate decreases in Europe.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "Rate & Pricing & Market Conditions"}\n'
    "Reason: Named Global Market Index figure with QoQ rate movement across multiple lines -- market conditions data.\n\n"

    "[ex_28] In Denmark, Allianz was unable to quote for Royal Greenland due to lack of resources. "
    "Allianz declined Oterra due to required exclusions; ARDO Foods LTA moved to 2027 remarketing.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "Rate & Pricing & Market Conditions"}\n'
    "Reason: Named country-level capacity constraints and appetite limitations impacting specific accounts -- local market conditions.\n\n"

    "[ex_29] Chubb Casualty new business: 71 submissions, 57 quoted (80%), 13 bound (23%). "
    "Quoted premium $1.23m vs bound $362k -- bind rate declining from 26% prior year to 23%.\n"
    '-> {"umbrella_tag": "Key Takeaways", "sub_tag": "Rate & Pricing & Market Conditions"}\n'
    "Reason: Submission-to-bind conversion metrics revealing competitive pricing pressure -- rate environment embedded in bind ratios.\n"
)
