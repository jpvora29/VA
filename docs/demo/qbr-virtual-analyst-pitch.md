# QBR Virtual Analyst

**A quarterly business review pack, built in minutes instead of days — and every sentence in it can be traced back to a number.**

This document is both a business case and a six-minute demo script. Read sections 1 to 6 before you present. Section 7 is the script itself, written to be said out loud.

---

## 1. The problem, in business terms

A quarterly business review takes several days of skilled work to produce. Very little of that work is analysis. Most of it is assembly.

Someone pulls the extract. Someone rebuilds the same chart that was built last quarter. Someone rewrites last quarter's commentary with this quarter's numbers. Then the whole pack is checked three times, because a single wrong figure in front of a client costs more than the pack is worth.

That creates three separate business costs.

**The cost of time.** Experienced people spend their most valuable days formatting slides instead of advising clients. This is the cost that is easiest to measure and the least interesting of the three.

**The cost of coverage.** Because a full review is expensive to produce, only the largest clients receive one. Everybody else gets a shorter pack. The decision is driven by capacity, not by priority — and the clients we serve least well are usually the ones most likely to leave.

**The cost of risk.** Every pack we produce carries the risk of a transposition error, a stale figure, or a paragraph that no longer matches the chart beside it. Today we manage that risk by checking everything by hand, several times, which is exactly why the process is so slow.

---

## 2. What the QBR Virtual Analyst does

The tool takes the questions a person would normally answer in their head — who is this for, which market, which products, which peer group — and turns them into a finished pack.

It is built from four parts that share one engine and one set of numbers.

**The QBR Generator** builds the pack. You answer five questions on a setup page, and it produces the full deck: executive summary, highlights, trading summary, portfolio analysis, ranking, growth quadrant, SWOT, and the per-carrier breakdown. The pack repeats automatically for every product and every country you have selected.

**The Canvas** is where you review and edit the pack before it leaves the building. This is where a named person still signs the work off, exactly as they do today.

**The Chatbot** answers the questions that the pack did not anticipate. It runs on the same engine and the same data as the deck, so the answer given in a meeting cannot contradict the answer printed on the slide.

**The Minutes of Meeting creator and the Deck Recap** handle what happens around the meeting. One turns the discussion into decisions, owners and dates. The other turns a sixty-page pack into the single page that a senior leader will actually read.

The most important design decision is this one: **the model never produces a number.** Every figure is calculated by the engine from governed data. The model writes the sentences around those figures, and then every claim it makes is checked back against the same data. If a sentence cannot be traced to a number, it does not reach the page.

---

## 3. What this is worth to each part of the business

| If you are | What changes for you | Why it matters |
|---|---|---|
| **A P&L owner** | Coverage stops being a headcount decision. The same team can produce full reviews for far more of the book. | You extend proper client coverage without adding people. |
| **A client relationship leader** | Every client receives the same standard of review, every quarter. | Quality stops depending on which analyst happened to be free. |
| **An analyst or deck builder** | You stop rebuilding charts and retyping paragraphs. You review instead. | Your time moves from assembly to judgement, which is what you were hired for. |
| **A risk or compliance owner** | Every number in every pack traces back to governed data, and no competitor is ever named in client-facing output. | The controls are enforced by the system rather than by an author's memory on a Friday afternoon. |
| **The client or carrier** | They receive a benchmarked view of their own portfolio, with commentary they can question. | They can challenge any sentence, because every sentence points at the figure behind it. |

---

## 4. Current scope — what is live today

The following is working now and is what you will see in the demo.

- The pack is built from our governed data: premium data and the carrier survey, cut by country, product and year.
- Peer benchmarks are set market by market, because the competitive set in one country is not the competitive set in another.
- Client-facing output shows the peer group only as an aggregate. No competitor is ever named. This is enforced in the pipeline, not left to the person writing the slide.
- Commentary is written automatically and then verified against the underlying data before it is allowed onto the page.
- The finished pack exports into our existing PowerPoint template, with the structure repeating for each selected product and country.
- The chatbot answers questions against the same engine that produced the pack.

---

## 5. Envisioned scope — what comes next

**Next.** Any template becomes a valid input, so a client's own house format can be filled as easily as ours. Any dataset becomes a valid input, so a review can be built on a client's own extract when the answer does not live in our governed data.

**After that.** The meeting itself. Minutes are produced from the discussion so that commitments are tracked rather than remembered, and a one-page recap is generated from the finished pack so that senior readers get the story without reading sixty slides.

> **Status note for the presenter:** the Minutes of Meeting creator and the Deck Recap generator are not yet built in the main codebase. If they are not ready to demonstrate on the day, describe them once as planned scope and give the extra minute to the Canvas segment instead. Never demonstrate something that is not there — one caught overclaim will cost you the credibility of everything else you showed.

---

## 6. The financial impact

Fill every bracket with real figures before you present. The argument only works when the numbers belong to the audience, and a senior audience will test the first number you give them. Present the lines in this order.

| Line | How to say it |
|---|---|
| **Coverage today** | We produce full reviews for **[X]** of our **[Y]** accounts. Everybody else receives a shorter pack, and that is a capacity decision rather than a priority decision. |
| **The effort behind it** | **[N]** people spend **[H]** hours on each pack, across **[D]** packs a quarter. That is **[N × H × D × 4]** hours a year. |
| **What that costs** | At a loaded rate of **[rate]** an hour, we are spending **[£X]** a year on experienced people building slides rather than advising clients. |
| **What we get back** | Setup and review takes minutes rather than days. Even if we only recover **[70–85%]** of that time, it returns **[£Y]**, or **[Z]** analyst-days a year. |
| **Where the time goes** | That is **[N × D × 4]** additional client conversations we are genuinely prepared for, or full coverage extended down to **[tier]** with no new headcount. |
| **The risk we remove** | A wrong figure in front of a client is a risk we currently manage by checking everything three times. Verified commentary removes that category of error rather than reducing it. |
| **What it costs to find out** | One market, one carrier, and one day of the data team's time. We measure the pilot on cycle time and coverage. |

**If you are pushed for a payback figure you do not have, do not guess.** Say: *"Give me your pack count and your loaded rate, and you will have the full number tonight."* Then send it that night. A precise follow-up earns more trust than a confident estimate, and an estimate that later turns out to be wrong can cost you the sponsor.

---

## 7. The six-minute demo script

Total running time is five minutes and fifty seconds, which leaves a small buffer. Every line in *italics* is meant to be said out loud. Every line marked **DO** is an instruction for you, not something to say.

### Segment 1 — The opening (0:00 – 1:30)

**DO:** Have the Setup page on screen before you start. Do not open on a title slide. You are not presenting a tool yet.

> *"Before I show you anything, I want to ask you one question. How many of our clients receive a genuine review every quarter? Not a deck — a review."*
>
> **DO:** Pause here and let somebody answer.
>
> *"My guess is that our largest accounts receive one, and everybody else receives a shorter version. That is not because we care less about them. It is because we do not have the people. And the clients we serve least well are usually the ones who leave."*
>
> *"So let me tell you what this changes for each of you. If you own the P&L, you can cover far more of the book without hiring anyone. If you run client relationships, every client receives the same standard of review rather than depending on which analyst was available. And if you own risk, every number in every pack can be traced back to our own governed data, so nothing on the page is a guess."*
>
> *"Today this runs on our premium and survey data, cut by market and by product, with peer benchmarks set for each market, and it exports straight into our own template. That part is live. Next comes any template and the client's own data, along with an analyst you can question during the meeting itself. After that, the meeting writes itself up."*
>
> *"The financial case is straightforward. We have **[N]** people spending **[H]** hours on each pack, across **[D]** packs a quarter. That is **[£X]** a year of experienced people building slides. We will get most of that back. But honestly, that is the smaller win. The larger win is **[N × D × 4]** more client conversations that we are properly prepared for, from exactly the same team."*

**Why this works:** you have priced their current way of working, in their own numbers, before showing a single feature. Everything that follows is them buying time back rather than buying software.

### Segment 2 — The QBR Generator (1:30 – 2:45)

> *"I am going to show you the input rather than the output, because the input is where all the control sits. There are five questions here, and one of them is a compliance rule."*
>
> **DO:** Set audience to *Executive*, then depth to *Concise*.
>
> *"The first two are who the pack is for and how deep it goes. The board version was never the same as the deal team version, and now that is a setting rather than an argument."*
>
> **DO:** Set data source to *GPR + Carrier Survey*. Hover over the *Custom data* option, but do not click it.
>
> *"This is where the figures come from. There is one governed source behind every pack we produce, rather than fourteen different extracts sitting on fourteen different laptops. And if the answer lives in a file we do not hold yet, that file can be uploaded and used instead."*
>
> **DO:** Select country, then product, then year. Point out that each list gets shorter as you go.
>
> *"This is the scope. Notice that each list only offers what the selection above it actually contains, which means you cannot build a pack for a market that has no data behind it. That is a deliberate guardrail rather than a convenience."*
>
> **DO:** Open the peers panel. Take this beat slowly — it is the most important one in the segment.
>
> *"Peers are chosen market by market, because the competitive set in one country is not the competitive set in another. And in anything a client will see, the benchmark is shown as an aggregate. We never name a competitor. That rule lives inside the system, so it does not depend on the judgement of whoever wrote the slide."*
>
> **DO:** Open the template preview, show the sections and the assembly axis, then click *Generate*.
>
> *"And this is what it is about to build: executive summary, highlights, trading summary, portfolio and ranking, growth quadrant, SWOT and the carrier breakdown, repeating for every product and every country I selected. I have not typed a single number. I answered five questions, and the pack is the result of those answers."*

### Segment 3 — The Canvas (2:45 – 3:45)

**DO:** Switch to the pre-generated pack in your second tab. Land on the *Trading summary* page.

> *"This is the page that normally costs somebody an afternoon. The chart is calculated, the table is calculated, and this paragraph was written for it."*
>
> *"Which brings us to the real question, and I would rather ask it than wait for one of you to ask it. Who is responsible for a paragraph that a machine wrote?"*
>
> **DO:** Trace one sentence back to the figure that supports it.
>
> *"There are three parts to the answer. First, the model never creates a number — every figure comes from our governed data. Second, every claim the model makes is checked back against that data, and if a claim cannot be traced, it never reaches the page. Third, a person still reviews and signs the pack, right here, before it leaves the building. So responsibility sits exactly where it sits today, with a named human being. The only difference is that they are now reviewing rather than retyping."*
>
> **DO:** Move to the growth quadrant. Give it one breath, then move on.
>
> *"And this is the page you would actually use in the meeting. It shows where we are winning, where we are paying for share, and where somebody is quietly taking our book. The same method is applied to every carrier, every quarter, which is what makes this a management report rather than a collection of opinions."*

**Why this works:** the most senior person in the room is not worried about quality. They are worried about accountability. If you answer that before they raise it, you remove the only objection that can stop this outright.

### Segment 4 — The Chatbot (3:45 – 4:30)

> *"A pack can only answer the questions we thought of in advance. It never answers the one that gets asked across the table."*
>
> **DO:** Type: *"Which markets grew premium fastest but scored lowest on broker feedback?"* Run this exact question before the demo so the first live answer is not the slow one.
>
> *"You get the numbers, the chart, and the data behind them, and all of it comes from the same engine that built the pack. That means the answer given in the room cannot contradict the answer printed on the slide. Nothing damages our credibility faster than two versions of the same number, and this is how that stops happening."*

### Segment 5 — Minutes of Meeting (4:30 – 5:00)

**DO:** Show the transcript going in and the structured minutes coming out. Point at the owners and the dates.

> *"Every review ends with commitments, and most of those commitments are never chased. This takes the discussion and returns the decisions, the owners and the dates, in our own format, before people have left the room. Commitments we can track are worth considerably more than notes we can file."*

### Segment 6 — The Deck Recap (5:00 – 5:30)

**DO:** Show the finished pack going in and the one-page recap coming out.

> *"This last one is aimed directly at the senior people in this room. That pack runs to sixty pages, and you will read one of them. This reads the finished deck and writes that page for you: the story, the three numbers that matter, and the talking points for whoever ends up presenting it. Do that across the whole book and you have a quarterly view of every client relationship on a single screen."*

### Segment 7 — The close (5:30 – 5:50)

> *"Six minutes ago we had an empty form. We now have a complete pack, commentary that has been checked line by line, an analyst you can question, a set of minutes and a one-page summary. The quarter itself takes twelve weeks. Reporting on it should not take three of them."*
>
> *"So I am asking for three things. A named sponsor, one market and one carrier for next quarter, and one day of the data team's time. We will measure the pilot on cycle time and on coverage. If it does not move both of them, we stop — and you will have spent one day finding that out."*

**DO:** Stop talking after the ask. The silence is doing the work.

---

## 8. Objections, and how to answer them

Keep every answer short. At senior level, a long answer sounds like doubt.

| If they say | Say this |
|---|---|
| *"Who is responsible if it is wrong in front of a client?"* | The same person who is responsible today: the reviewer who signs it off. The difference is that they are now checking a traceable number instead of retyping one. |
| *"Can I really trust a machine with our numbers?"* | The model never produces a number. It writes sentences around figures the engine has calculated, and every claim is then checked against the data. If a claim cannot be traced, it never reaches the page. |
| *"Our template is different."* | That is fine, because the template is an input rather than a limitation. You give it yours and it fills yours. |
| *"Peer information is sensitive."* | Client-facing output shows peer groups as an aggregate only, and no competitor is ever named. The system enforces that rule. I am happy to walk your risk team through it separately. |
| *"Our data is not in your system."* | Upload the file, map the columns once, and the same pipeline runs on your data. |
| *"Why build this rather than buy something?"* | Nothing available off the shelf understands our peer rules, our template or our data. That knowledge is the actual product; everything else is plumbing. |
| *"Why now?"* | The coverage gap is widening, and this is the first year that the verification has been good enough to put a machine-written sentence in front of a client. |
| *"Does this replace analysts?"* | It replaces the assembly work, not the judgement. Your analysts stop building slide 34 and start arguing about what slide 34 actually means. |
| *"What if the key person leaves?"* | Today that knowledge sits in one analyst's head and their spreadsheet. Here it sits in rules and templates that anyone can read. This lowers key-person risk rather than creating it. |
| *"Will the team actually use it?"* | It removes the part of the job they complain about most. The genuine risk is that people trust it too quickly, which is exactly why human review stays mandatory. |
| *"How do we scale it beyond a pilot?"* | Adding a market is configuration rather than development. That is precisely why the template and the peer list are inputs. |
| *"What does the pilot cost?"* | One market, one carrier and one day of the data team's time, measured on cycle time and coverage. |

---

## 9. The ask

Ask for exactly three things, and ask for them at the very end.

1. **A named sponsor** who owns the outcome.
2. **One market and one carrier** for next quarter's pack.
3. **One day of the data team's time** to connect and check the source.

Then state the measure and the exit: the pilot is judged on cycle time and coverage, and if it does not move both, it stops. A small, dated, reversible commitment is far easier for a senior audience to approve than an open-ended one.

---

## 10. Pre-flight checklist — fifteen minutes before

A demo this short has no room to recover from a problem. Every item below has ruined a demo at some point.

1. **Pre-generate the pack in a second tab.** Click Generate live so they see it start, then cut across to the finished version. Never let a senior audience watch a loading spinner.
2. **Warm the cache and run the chatbot question once**, so that the first live answer is not the slow one.
3. **Choose a carrier with a genuine story** — real growth in one market and a clear weakness in another. A flat portfolio makes a strong tool look ordinary.
4. **Check that no competitor name is visible anywhere on screen.** One named peer and the next twenty minutes will be about governance instead of value.
5. **Confirm the peer set is populated** for the market you are demonstrating.
6. **Pre-load the transcript and the recap output.** Those two segments last thirty seconds each and cannot survive a file dialog.
7. **Close every other tab, silence notifications**, increase the browser zoom by one step, and match the theme to the room's screen.
8. **Know who in the room signs the decision** and aim segment 3 and segment 6 directly at them.
9. **Prepare a fallback.** If the demo fails completely, talk through the accountability argument in segment 3 from memory. That is the part that actually sells.
10. **Rehearse the closing ask word for word**, and practise stopping once you have made it.
