"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
your job is to fill in handle_query() so it calls run_agent() and maps
the session results to the three output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import reset_style_memory, run_agent
from tools import compare_price
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


APP_CSS = """
.result-panel {
    min-height: 18rem;
    overflow: hidden;
}

.result-title {
    margin: -1rem -1rem 0 !important;
    padding: 0.75rem 1rem !important;
    background: var(--background-fill-secondary);
    border-bottom: 1px solid var(--border-color-primary);
}

.result-title h3 {
    margin: 0 !important;
}

.result-output {
    padding: 1rem !important;
    overflow-x: auto;
}

.style-profile {
    margin: 0.5rem 0 1rem !important;
    padding: 0.75rem 1rem !important;
    background: var(--background-fill-secondary);
    border: 1px solid var(--border-color-primary);
    border-radius: var(--radius-md);
}

.style-profile p {
    margin: 0 !important;
}

.outfit-output table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    margin: 0.75rem 0 1rem;
}

.outfit-output th,
.outfit-output td {
    padding: 0.75rem 0.875rem !important;
    text-align: left !important;
    vertical-align: top;
    border-right: 1px solid var(--border-color-primary);
    border-bottom: 1px solid var(--border-color-primary);
}

.outfit-output th:first-child,
.outfit-output td:first-child {
    border-left: 1px solid var(--border-color-primary);
}

.outfit-output th {
    background: var(--background-fill-secondary);
    border-top: 1px solid var(--border-color-primary);
    font-weight: 600;
}

.outfit-output th:first-child {
    border-top-left-radius: var(--radius-md);
}

.outfit-output th:last-child {
    border-top-right-radius: var(--radius-md);
}

.outfit-output tbody tr:last-child td:first-child {
    border-bottom-left-radius: var(--radius-md);
}

.outfit-output tbody tr:last-child td:last-child {
    border-bottom-right-radius: var(--radius-md);
}
"""


# ── query handler ─────────────────────────────────────────────────────────────

EMPTY_STYLE_PROFILE = '**Your Style Profile:** _No preferences learned yet._'


def _format_style_profile(
    styles: list[str] | None,
    remembered_size: str | None = None,
) -> str:
    """Format learned preferences as a compact, readable Markdown line."""
    if styles:
        readable = ' • '.join(
            style if style == 'Y2K' else style.title()
            for style in styles
        )
        profile = f'**Your Style Profile:** {readable}'
    else:
        profile = EMPTY_STYLE_PROFILE
    if remembered_size is not None:
        profile += f'  \n**Remembered size:** {remembered_size}'
    return profile

def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Args:
        user_query:     The text the user typed into the search box.
        wardrobe_choice: Either "Example wardrobe" or "Empty wardrobe (new user)".

    Returns:
        A tuple of three strings:
            (listing_text, outfit_suggestion, fit_card)
        Each string maps to one of the three output panels in the UI.

    Behavior:
        1. Guard against an empty query (return early with an error message).
        2. Select the wardrobe based on wardrobe_choice.
        3. Call run_agent() with the query and selected wardrobe.
        4. If session["error"] is set, return the error in the first panel
           and empty strings for the other two.
        5. Otherwise, format session["selected_item"] into a readable listing_text
           string and return it along with session["outfit_suggestion"] and
           session["fit_card"].
    """
    return handle_query_with_state(user_query, wardrobe_choice)[:3]


def handle_query_with_state(user_query: str, wardrobe_choice: str) -> tuple:
    """Return result panels, session, cleared comparison, and style profile."""
    if not user_query or not user_query.strip():
        return (
            'Please describe the clothing item you are looking for.', '', '',
            {}, '', EMPTY_STYLE_PROFILE,
        )
    wardrobe = (
        get_empty_wardrobe() if wardrobe_choice == 'Empty wardrobe (new user)'
        else get_example_wardrobe()
    )
    session = run_agent(query=user_query, wardrobe=wardrobe)
    style_profile = _format_style_profile(
        session.get('style_profile'), session.get('remembered_size'),
    )
    if session['error'] is not None:
        return session['error'], '', '', session, '', style_profile
    item = session['selected_item']
    listing_text = (
        f"**{item['title']}**\n\n"
        f"- **Size:** {item['size']}\n"
        f"- **Condition:** {item['condition'].title()}\n"
        f"- **Price:** ${item['price']:.2f}\n"
        f"- **Platform:** {item['platform']}\n\n"
        f"{item['description']}"
    )
    return (
        listing_text, session['outfit_suggestion'], session['fit_card'],
        session, '', style_profile,
    )


def handle_price_comparison(session: dict | None) -> str:
    """Read the latest selected listing from this user's Gradio state."""
    session = session or {}
    return compare_price(session.get('selected_item'), session.get('parsed'))


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        session_state = gr.State({})
        gr.HTML(f"<style>{APP_CSS}</style>")
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        style_profile_output = gr.Markdown(
            EMPTY_STYLE_PROFILE,
            elem_classes=['style-profile'],
        )

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=["Example wardrobe", "Empty wardrobe (new user)"],
                value="Example wardrobe",
                label="Wardrobe",
                scale=1,
            )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            with gr.Column(variant="panel", elem_classes=["result-panel"]):
                gr.Markdown("### 🛍️ Top listing found", elem_classes=["result-title"])
                listing_output = gr.Markdown(
                    container=False,
                    elem_classes=["result-output", "listing-output"],
                )
            with gr.Column(variant="panel", elem_classes=["result-panel"]):
                gr.Markdown("### 👗 Outfit idea", elem_classes=["result-title"])
                outfit_output = gr.Markdown(
                    container=False,
                    elem_classes=["result-output", "outfit-output"],
                )
            with gr.Column(variant="panel", elem_classes=["result-panel"]):
                gr.Markdown("### ✨ Your fit card", elem_classes=["result-title"])
                fitcard_output = gr.Markdown(
                    container=False,
                    elem_classes=["result-output", "fitcard-output"],
                )

        with gr.Column(variant="panel"):
            gr.Markdown('### Price Comparison Tool', elem_classes=['result-title'])
            compare_btn = gr.Button('Price Comparison Tool')
            comparison_output = gr.Markdown(elem_classes=['result-output', 'outfit-output'])

        compare_btn.click(
            fn=handle_price_comparison,
            inputs=[session_state], outputs=[comparison_output],
            concurrency_id='fitfindr-workflow', concurrency_limit=1,
        )

        gr.Examples(
            examples=[[q, "Example wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        submit_btn.click(
            fn=handle_query_with_state,
            inputs=[query_input, wardrobe_choice],
            outputs=[
                listing_output, outfit_output, fitcard_output, session_state,
                comparison_output, style_profile_output,
            ],
            concurrency_id='fitfindr-workflow', concurrency_limit=1,
        )
        query_input.submit(
            fn=handle_query_with_state,
            inputs=[query_input, wardrobe_choice],
            outputs=[
                listing_output, outfit_output, fitcard_output, session_state,
                comparison_output, style_profile_output,
            ],
            concurrency_id='fitfindr-workflow', concurrency_limit=1,
        )

    return demo


if __name__ == "__main__":
    reset_style_memory()
    demo = build_interface()
    demo.launch()
