"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from groq import APIError

from tools import search_listings, suggest_outfit, create_fit_card


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """Extract explicit filters with regex; use the first sentence as the search."""
    price_pattern = re.compile(
        r'\b(?:under|below|up to|less than|at most|max(?:imum)?(?: price)?(?: of)?)'
        r'\s*\$?\s*(\d+(?:\.\d+)?)\b', re.IGNORECASE,
    )
    size_pattern = re.compile(
        r'\b(?:in\s+)?size\s+('
        r'one\s+size|(?:US\s*)?\d+(?:\.\d+)?|W\d+(?:\s+L\d+)?|'
        r'XXXS|XXS|XS|S/M|M/L|L/XL|XXXL|XXL|XL|S|M|L)\b',
        re.IGNORECASE,
    )
    price = price_pattern.search(query)
    size = size_pattern.search(query)
    description = price_pattern.sub('', size_pattern.sub('', query))
    description = re.split(r'[!?]|\.(?:\s|$)', description, maxsplit=1)[0]
    description = re.sub(
        r"^\s*(?:(?:i['’]m|i am)\s+)?(?:looking for|searching for|i want|i need|find me)\s+(?:an?\s+)?",
        '', description, flags=re.IGNORECASE,
    )
    description = ' '.join(description.strip(' ,.;:').split())
    return {
        'description': description,
        'size': size.group(1).upper() if size else None,
        'max_price': float(price.group(1)) if price else None,
    }


def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    Workflow:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)
    if not query or not query.strip():
        session['error'] = 'Please describe the clothing item you are looking for.'
        return session

    session['parsed'] = _parse_query(session['query'])
    if not session['parsed']['description']:
        session['error'] = 'Please include an item description along with your filters.'
        return session

    stage = 'search listings'
    try:
        session['search_results'] = search_listings(**session['parsed'])
        if not session['search_results']:
            session['error'] = (
                'No listings match your request. Try broadening the description, '
                'removing the size filter, or increasing the maximum price.'
            )
            return session

        session['selected_item'] = session['search_results'][0]
        stage = 'suggest an outfit'
        session['outfit_suggestion'] = suggest_outfit(
            new_item=session['selected_item'], wardrobe=session['wardrobe'],
        )
        if not isinstance(session['outfit_suggestion'], str) or not session['outfit_suggestion'].strip():
            raise ValueError('No usable outfit suggestion was returned.')

        stage = 'create a fit card'
        session['fit_card'] = create_fit_card(
            outfit=session['outfit_suggestion'], new_item=session['selected_item'],
        )
        if not isinstance(session['fit_card'], str) or not session['fit_card'].strip():
            raise ValueError('No usable fit card was returned.')
    except (APIError, OSError, ValueError, KeyError, TypeError):
        # Keep provider responses and credentials out of user-facing errors.
        session['error'] = f'Unable to {stage}. Check your configuration and inputs, then try again.'
        session['outfit_suggestion'] = None
        session['fit_card'] = None
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
