# FitFindr — Starter Kit

This starter kit contains everything you need to begin Project 2.

## What's Included

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 82 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe
├── utils/
│   └── data_loader.py         # Helper functions for loading the data
├── planning.md                # Your planning template — fill this out first
└── requirements.txt           # Python dependencies
```

## Setup

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (get a free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

## The Mock Listings Dataset

`data/listings.json` contains 82 mock secondhand listings across categories (tops, bottoms, outerwear, shoes, accessories) and styles (vintage, y2k, grunge, cottagecore, streetwear, and more).

The dataset includes groups of similarly styled, same-size items to test comparisons:
graphic tees in S/M/L/XL; flannel shirts in M/L; track jackets in M/L; baggy jeans
in W30/W32; chunky sneakers in US 8/9; black combat boots in US 8; and linen blazers
in M. Each added group includes three prices, with the same condition (good), so
comparisons can demonstrate different assessments without relaxing size filters.

Each listing has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`.

Load it with:
```python
from utils.data_loader import load_listings
listings = load_listings()
```

## The Wardrobe Schema

`data/wardrobe_schema.json` defines the format your agent uses to represent a user's existing wardrobe. It includes:

- `schema`: field definitions for a wardrobe item
- `example_wardrobe`: a sample wardrobe with 10 items you can use for testing
- `empty_wardrobe`: a starting template for a new user

Load an example wardrobe with:
```python
from utils.data_loader import get_example_wardrobe
wardrobe = get_example_wardrobe()
```

## Tool Inventory

### Style Profile Memory

FitFindr keeps a lightweight, single-user style history in `memory.md`. The file
is created in the project root and reset each time the app is started with
`python app.py`, so it represents only the current local app run. It is ignored
by Git and is intended for the project's one-browser-user demonstration.

For every valid fashion query, the agent records the raw query and extracts a
concise set of recognizable preferences such as vintage, streetwear, relaxed,
oversized, minimalist, preppy, business casual, sporty, Y2K, neutral colors,
colorful, formal, grunge, and boho. Related phrases are normalized—for example,
`baggy jeans` or `chunky sneakers` imply streetwear. New preferences are merged
into the existing profile without case-insensitive duplicates. A no-results
search still records its query and useful style preferences. The memory also
stores the most recently mentioned normalized size. If a later query omits a
size, the agent applies that remembered size to `search_listings()`; an explicit
new size replaces the old value.

After a successful search and outfit generation, the same document receives the
actual selected listing dictionary from `session["selected_item"]` and the exact
outfit text from `session["outfit_suggestion"]`. Before each outfit request,
`run_agent()` reads the document and passes it through the optional
`style_memory` argument of `suggest_outfit(new_item, wardrobe, style_memory='')`.
The LLM is instructed to use relevant previously learned preferences, making
memory affect later recommendations rather than merely storing history. Missing,
empty, malformed, or unwritable memory falls back to a fresh in-memory template
without crashing the main search and styling workflow.

For example:

1. `Find me a vintage graphic tee size M with a relaxed streetwear look.` records
   vintage, streetwear, relaxed, and size M, followed by the selected tee and outfit.
2. `Find me a jacket under $60.` does not repeat those preferences, but the
   search automatically uses size M, and the outfit model receives the first
   interaction and styles the jacket for the remembered vintage, relaxed
   streetwear profile.

The compact **Your Style Profile** panel appears below the app introduction and
above the query controls. It updates after every query to show the learned style
preferences and the currently remembered size; users do not enter this profile
separately.

This deliberately simple version is scoped to one local browser user. It does
not isolate multiple simultaneous users; restarting the app begins a new memory.

### Price Comparison Tool

Click **Price Comparison Tool** below the result panels and above **Try these queries**
after searching. It uses the selected listing retained in your browser session; no
second item entry or LLM call is needed. A new search clears the previous comparison,
and an unsuccessful search clears the selection.

`compare_price(selected_item: dict | None, parsed: dict | None = None) -> str` in `tools.py` returns a Markdown
assessment with reasoning and a table of comparable listings, or a helpful message
when no item is selected or fewer than two comparables exist.

Comparables come from `load_listings()`, excluding the selected ID. They must share
the category and garment type. A fixed, case-insensitive vocabulary recognizes
types in titles first, then style tags: tees/T-shirts, jeans, shorts, pants/trousers,
skirts, dresses, hoodies, sweatshirts/crewnecks, cardigans, vests, blazers,
jackets/windbreakers/bombers/shackets, shirts/polos/button-downs/henleys, tops,
sneakers, boots, Mary Janes, belts, hats, and bags. An unrecognized type yields
insufficient data. Broad style words such as "vintage" alone do not qualify a match.
The saved search description and size are passed to `search_listings()` with
`max_price=None`, reusing its keyword scoring and size rules. Zero-keyword matches
are dropped; qualifying comparables are shown best-first, and all of them enter
the median. Requested `L` matches `L` and `L/XL`, but not `XL`. Search also recognizes
small, medium, large, extra small, and extra large (including hyphenated forms).
If no size was requested, comparisons allow all sizes. Size restrictions are never
silently relaxed when data is insufficient. Conditions, brands, and platforms may
differ; prices are not adjusted for those differences. The original search budget
is deliberately not applied, so more expensive comparable items remain in the
benchmark. The output explains the size criterion and budget exclusion.

With at least two other matches, the tool computes their median price and
`100 × (selected price − median) / median`:

| Label | Rule |
|---|---|
| Good Deal | More than 10% below the median |
| Fair Price | Within 10% of the median, including exactly −10% and +10% |
| Bad Deal | More than 10% above the median; relatively expensive |

Every assessment shows the selected price, median, percentage difference, count,
observed price range, and supporting listings with prices, conditions, and sizes.
These labels describe mock dataset asking prices, not independently verified market
value. With no size restriction, the $18 Y2K Baby Tee is 25.0% below the $24.00
median of the other tees in the expanded dataset, so it receives **Good Deal**.

To try all three labels in the app, search for each of these, then click the
comparison button (the title keywords select the intended listing):

| Search query | Expected assessment |
|---|---|
| `90s track jacket teal stripe size M` | Good Deal ($28) |
| `90s track jacket burgundy stripe size M` | Fair Price ($44) |
| `90s track jacket forest stripe size M` | Bad Deal ($64) |

Other useful queries include `large vintage graphic tee under $30`,
`vintage flannel shirt size M`, and `black combat boots size 8`.

Your README submission must document each tool's name, inputs, and return value. **These must exactly match your actual function signatures in `tools.py`.** Your documented interfaces will be checked against your actual function signatures in `tools.py` — if the parameter count or types contradict what's in the code, you may not receive full credit for that tool.

---

## Interaction Walkthrough

<!-- Walk through a complete interaction step by step: natural language query → each tool call (and why) → final fit card.
     Walk through this carefully — it's how graders follow your agent's reasoning without a live demo.
     Use a specific example — do not leave this as a template. -->

**User query:**

**Step 1 — Tool called:**
- Tool:
- Input:
- Why this tool:
- Output:

**Step 2 — Tool called:**
- Tool:
- Input:
- Why this tool:
- Output:

**Step 3 — Tool called:**
- Tool:
- Input:
- Why this tool:
- Output:

**Final output to user:**

---

## Error Handling and Fail Points

<!-- For each tool, describe the specific failure mode and what your agent does in response.
     This maps to the error handling section of the rubric (F5-C1). -->

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | | |
| `suggest_outfit` | | |
| `create_fit_card` | | |

---

## Spec Reflection

<!-- Answer both questions with at least 2–3 sentences each. -->

**One way planning.md helped during implementation:**

**One divergence from your spec, and why:**

---

## Where to Start

1. **Read `planning.md` and fill it out before writing any code.**
2. Verify the data loads correctly by running `python utils/data_loader.py`.
3. Build and test each tool individually before connecting them through your planning loop.

Your implementation files go in this same directory. There's no required file structure for your agent code — organize it however makes sense for your design.
