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

import json
import re
from pathlib import Path

from groq import APIError

from tools import search_listings, suggest_outfit, create_fit_card
from tools import SIZE_WORDS, normalize_size


MEMORY_PATH = Path(__file__).resolve().parent / 'memory.md'
MEMORY_TEMPLATE = (
    '# Style Profile Memory\n\n'
    'This document is reset whenever the local app starts. It records the style '\
    'preferences and recommendations from the current app run.\n\n'
    '## Learned Style Profile\n\n'
    'Preferences: None yet\n\n'
    'Last size: None yet\n\n'
    '## Interaction History\n'
)

# Ordered so the profile remains stable and readable across interactions.
STYLE_PATTERNS = (
    ('vintage', r'\b(?:vintage|retro)\b'),
    ('streetwear', r'\bstreetwear\b|\bbaggy jeans?\b|\bchunky sneakers?\b'),
    ('relaxed', r'\b(?:relaxed|loose[ -]?fit)\b'),
    ('oversized', r'\boversized\b'),
    ('minimalist', r'\bminimal(?:ist)?\b'),
    ('preppy', r'\bpreppy\b'),
    ('business casual', r'\bbusiness casual\b'),
    ('casual', r'\bcasual\b'),
    ('sporty', r'\b(?:sporty|athleisure|athletic)\b'),
    ('Y2K', r'\by2k\b'),
    ('neutral colors', r'\b(?:neutral colors?|neutral palette|earth tones?)\b'),
    ('colorful', r'\b(?:colorful|bright colors?|bold colors?)\b'),
    ('formal', r'\bformal\b'),
    ('grunge', r'\bgrunge\b'),
    ('boho', r'\b(?:boho|bohemian)\b'),
)


def reset_style_memory(memory_path: str | Path | None = None) -> Path:
    """Reset the single-user memory document for a new local app run."""
    path = Path(memory_path) if memory_path is not None else MEMORY_PATH
    path.write_text(MEMORY_TEMPLATE, encoding='utf-8')
    return path


def _extract_style_preferences(query: str) -> list[str]:
    """Extract a concise, deterministic set of style preferences from a query."""
    styles = [
        name for name, pattern in STYLE_PATTERNS
        if re.search(pattern, query, re.IGNORECASE)
    ]
    if 'business casual' in styles and 'casual' in styles:
        styles.remove('casual')
    return styles


def _read_style_memory(path: Path) -> str:
    """Read a valid memory document, initializing malformed or missing memory."""
    try:
        content = path.read_text(encoding='utf-8')
        if (
            content.startswith('# Style Profile Memory')
            and re.search(r'^Preferences:\s*.+$', content, re.MULTILINE)
            and re.search(r'^Last size:\s*.+$', content, re.MULTILINE)
        ):
            return content
        reset_style_memory(path)
        return MEMORY_TEMPLATE
    except FileNotFoundError:
        try:
            reset_style_memory(path)
        except OSError:
            pass
        return MEMORY_TEMPLATE
    except OSError:
        return MEMORY_TEMPLATE


def _profile_from_memory(content: str) -> list[str]:
    match = re.search(r'^Preferences:\s*(.+)$', content, re.MULTILINE)
    if not match or match.group(1).strip().casefold() == 'none yet':
        return []
    return [value.strip() for value in match.group(1).split(',') if value.strip()]


def _size_from_memory(content: str) -> str | None:
    match = re.search(r'^Last size:\s*(.+)$', content, re.MULTILINE)
    if not match or match.group(1).strip().casefold() == 'none yet':
        return None
    return normalize_size(match.group(1))


def _write_style_memory(path: Path, content: str) -> None:
    """Best-effort write: memory failures must not stop the fashion workflow."""
    try:
        path.write_text(content, encoding='utf-8')
    except OSError:
        pass


def _record_query(
    path: Path,
    query: str,
    explicit_size: str | None,
) -> tuple[str, list[str], str | None]:
    content = _read_style_memory(path)
    profile = _profile_from_memory(content)
    remembered_size = _size_from_memory(content)
    extracted = _extract_style_preferences(query)
    for style in extracted:
        if style.casefold() not in {saved.casefold() for saved in profile}:
            profile.append(style)
    profile_text = ', '.join(profile) if profile else 'None yet'
    content = re.sub(
        r'^Preferences:\s*.+$', f'Preferences: {profile_text}', content,
        count=1, flags=re.MULTILINE,
    )
    if explicit_size is not None:
        remembered_size = normalize_size(explicit_size)
        content = re.sub(
            r'^Last size:\s*.+$', f'Last size: {remembered_size}', content,
            count=1, flags=re.MULTILINE,
        )
    interaction_number = len(re.findall(r'^### Interaction \d+$', content, re.MULTILINE)) + 1
    clean_query = ' '.join(query.split())
    extracted_text = ', '.join(extracted) if extracted else 'None detected'
    if explicit_size is not None:
        size_text = f'{remembered_size} (new)'
    elif remembered_size is not None:
        size_text = f'{remembered_size} (remembered)'
    else:
        size_text = 'None'
    content = content.rstrip() + (
        f'\n\n### Interaction {interaction_number}\n\n'
        f'**Query:** {clean_query}\n\n'
        f'**Extracted styles:** {extracted_text}\n\n'
        f'**Size used:** {size_text}\n'
    )
    _write_style_memory(path, content)
    return content, profile, remembered_size


def _record_interaction_result(
    path: Path,
    selected_item: dict | None = None,
    outfit_suggestion: str | None = None,
    result: str | None = None,
) -> None:
    content = _read_style_memory(path).rstrip()
    if selected_item is not None:
        content += (
            '\n\n**Selected item:**\n\n```json\n'
            + json.dumps(selected_item, ensure_ascii=False, indent=2)
            + '\n```'
        )
    if outfit_suggestion is not None:
        content += f'\n\n**Outfit suggestion:**\n\n{outfit_suggestion.strip()}'
    if result is not None:
        content += f'\n\n**Result:** {result}'
    _write_style_memory(path, content + '\n')


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
        + SIZE_WORDS + r'|one\s+size|(?:US\s*)?\d+(?:\.\d+)?|W\d+(?:\s+L\d+)?|'
        r'XXXS|XXS|XS|S/M|M/L|L/XL|XXXL|XXL|XL|S|M|L)\b',
        re.IGNORECASE,
    )
    price = price_pattern.search(query)
    size = size_pattern.search(query)
    description = price_pattern.sub('', size_pattern.sub('', query))
    description = re.split(r'[!?]|\.(?:\s|$)', description, maxsplit=1)[0]
    word_size = re.search(r'\b' + SIZE_WORDS + r'\b', description, re.IGNORECASE)
    requested_size = normalize_size(size.group(1)) if size else None
    if requested_size is None and word_size:
        requested_size = normalize_size(word_size.group())
        description = description[:word_size.start()] + description[word_size.end():]
    description = re.sub(
        r"^\s*(?:(?:i['’]m|i am)\s+)?(?:looking for|searching for|i want|i need|find me)\s+(?:an?\s+)?",
        '', description, flags=re.IGNORECASE,
    )
    description = ' '.join(description.strip(' ,.;:').split())
    return {
        'description': description,
        'size': requested_size,
        'max_price': float(price.group(1)) if price else None,
    }


def run_agent(
    query: str,
    wardrobe: dict,
    memory_path: str | Path | None = None,
) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py
        memory_path: Optional path override used by tests. By default, use the
                     single-user `memory.md` in the project root.

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
    resolved_memory_path = Path(memory_path) if memory_path is not None else MEMORY_PATH
    session['memory_path'] = str(resolved_memory_path)
    session['style_profile'] = []
    if not query or not query.strip():
        session['error'] = 'Please describe the clothing item you are looking for.'
        return session

    session['parsed'] = _parse_query(session['query'])
    if not session['parsed']['description']:
        session['error'] = 'Please include an item description along with your filters.'
        return session

    explicit_size = session['parsed']['size']
    style_memory, session['style_profile'], session['remembered_size'] = _record_query(
        resolved_memory_path, session['query'], explicit_size,
    )
    if explicit_size is None and session['remembered_size'] is not None:
        session['parsed']['size'] = session['remembered_size']

    stage = 'search listings'
    try:
        session['search_results'] = search_listings(**session['parsed'])
        if not session['search_results']:
            _record_interaction_result(
                resolved_memory_path, result='No matching listing was found.',
            )
            session['error'] = (
                'No listings match your request. Try broadening the description, '
                'removing the size filter, or increasing the maximum price.'
            )
            return session

        session['selected_item'] = session['search_results'][0]
        stage = 'suggest an outfit'
        session['outfit_suggestion'] = suggest_outfit(
            new_item=session['selected_item'], wardrobe=session['wardrobe'],
            style_memory=style_memory,
        )
        if not isinstance(session['outfit_suggestion'], str) or not session['outfit_suggestion'].strip():
            raise ValueError('No usable outfit suggestion was returned.')

        _record_interaction_result(
            resolved_memory_path,
            selected_item=session['selected_item'],
            outfit_suggestion=session['outfit_suggestion'],
        )

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
