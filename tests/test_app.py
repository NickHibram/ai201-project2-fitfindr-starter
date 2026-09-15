from unittest.mock import Mock

import pytest

import app
from utils.data_loader import load_listings


@pytest.mark.parametrize('query', ['', ' \n '])
def test_empty_query_does_not_run_agent(monkeypatch, query):
    runner = Mock()
    monkeypatch.setattr(app, 'run_agent', runner)
    listing, outfit, card = app.handle_query(query, 'Example wardrobe')
    assert listing
    assert (outfit, card) == ('', '')
    runner.assert_not_called()


@pytest.mark.parametrize('choice', ['Example wardrobe', 'Empty wardrobe (new user)'])
def test_success_maps_session_to_panels(monkeypatch, choice):
    item = load_listings()[0]
    runner = Mock(return_value={
        'error': None, 'selected_item': item,
        'outfit_suggestion': 'Exact outfit.', 'fit_card': 'Exact caption.',
        'style_profile': ['vintage', 'streetwear', 'relaxed'],
    })
    monkeypatch.setattr(app, 'run_agent', runner)
    listing, outfit, card = app.handle_query('vintage jeans', choice)
    runner.assert_called_once()
    assert runner.call_args.kwargs['query'] == 'vintage jeans'
    wardrobe = runner.call_args.kwargs['wardrobe']
    assert bool(wardrobe['items']) == (choice == 'Example wardrobe')
    assert f"**{item['title']}**" in listing
    assert f"${item['price']:.2f}" in listing
    assert item['platform'] in listing
    assert (outfit, card) == ('Exact outfit.', 'Exact caption.')


def test_error_clears_other_panels(monkeypatch):
    monkeypatch.setattr(app, 'run_agent', Mock(return_value={'error': 'No matching listings.'}))
    assert app.handle_query('ballgown', 'Example wardrobe') == ('No matching listings.', '', '')


def test_comparison_uses_saved_session_and_clears_on_failed_search(monkeypatch):
    item = next(record for record in load_listings() if record['id'] == 'lst_002')
    session = {'error': None, 'selected_item': item, 'outfit_suggestion': 'Outfit', 'fit_card': 'Caption'}
    runner = Mock(return_value=session)
    monkeypatch.setattr(app, 'run_agent', runner)
    outputs = app.handle_query_with_state('tee', 'Example wardrobe')
    assert outputs[3] is session
    assert outputs[3]['selected_item'] is item
    assert outputs[4] == ''
    assert outputs[5] == '**Your Style Profile:** _No preferences learned yet._'
    assert '### Good Deal' in app.handle_price_comparison(outputs[3])
    runner.assert_called_once()
    runner.return_value = {
        'error': 'No matching listings.', 'selected_item': None,
        'style_profile': ['minimalist'],
    }
    failed = app.handle_query_with_state('ballgown', 'Example wardrobe')
    assert failed[3] is runner.return_value
    assert failed[4] == ''
    assert failed[5] == '**Your Style Profile:** Minimalist'
    assert 'search for an item first' in app.handle_price_comparison(failed[3])


def test_empty_search_resets_comparison_state():
    assert app.handle_query_with_state('', 'Example wardrobe')[3:] == (
        {}, '', '**Your Style Profile:** _No preferences learned yet._',
    )
    assert 'search for an item first' in app.handle_price_comparison(None)


def test_style_profile_output_updates_from_agent_session(monkeypatch):
    item = load_listings()[0]
    monkeypatch.setattr(app, 'run_agent', Mock(return_value={
        'error': None,
        'selected_item': item,
        'outfit_suggestion': 'Outfit.',
        'fit_card': 'Caption.',
        'style_profile': ['vintage', 'streetwear', 'Y2K'],
        'remembered_size': 'M',
    }))

    outputs = app.handle_query_with_state('vintage streetwear tee', 'Example wardrobe')

    assert outputs[5] == (
        '**Your Style Profile:** Vintage • Streetwear • Y2K  \n'
        '**Remembered size:** M'
    )


def test_comparison_receives_saved_query_filters(monkeypatch):
    item = load_listings()[1]
    parsed = {'description': 'graphic tee', 'size': 'L', 'max_price': 30}
    comparison = Mock(return_value='Size-aware assessment')
    monkeypatch.setattr(app, 'compare_price', comparison)
    assert app.handle_price_comparison({'selected_item': item, 'parsed': parsed}) == 'Size-aware assessment'
    assert comparison.call_args.args[0] is item
    assert comparison.call_args.args[1] is parsed


def test_comparison_button_before_examples_and_receives_state():
    interface = app.build_interface()
    components = interface.config['components']
    button = next(c for c in components if c['type'] == 'button' and c['props']['value'] == 'Price Comparison Tool')
    examples = next(c for c in components if c['type'] == 'dataset')
    assert components.index(button) < components.index(examples)
    state = next(c for c in components if c['type'] == 'state')
    comparison_event = next(d for d in interface.config['dependencies'] if (button['id'], 'click') in d['targets'])
    assert comparison_event['inputs'] == [state['id']]


def test_result_panels_keep_titles_and_render_markdown():
    """Catch missing headings or outputs that expose Markdown as raw text."""
    interface = app.build_interface()
    components = interface.config['components']
    title_values = {
        component['props'].get('value')
        for component in components if component['type'] == 'markdown'
    }
    assert {
        '### 🛍️ Top listing found',
        '### 👗 Outfit idea',
        '### ✨ Your fit card',
    } <= title_values

    output_classes = ('listing-output', 'outfit-output', 'fitcard-output')
    for output_class in output_classes:
        output = next(
            component for component in components
            if output_class in component['props'].get('elem_classes', [])
        )
        assert output['type'] == 'markdown'

    assert sum(
        component['type'] == 'column'
        and 'result-panel' in component['props'].get('elem_classes', [])
        for component in components
    ) == 3
    style_component = next(
        component for component in components
        if component['type'] == 'html' and '<style>' in component['props']['value']
    )
    assert '.outfit-output table' in style_component['props']['value']
    assert '.result-title' in style_component['props']['value']


def test_style_profile_is_above_query_input_and_updated_by_search_events():
    interface = app.build_interface()
    components = interface.config['components']
    profile = next(
        component for component in components
        if 'style-profile' in component['props'].get('elem_classes', [])
    )
    query = next(
        component for component in components
        if component['type'] == 'textbox'
        and component['props'].get('label') == 'What are you looking for?'
    )
    assert components.index(profile) < components.index(query)
    assert profile['props']['value'] == '**Your Style Profile:** _No preferences learned yet._'

    search_events = [
        dependency for dependency in interface.config['dependencies']
        if dependency.get('api_name', '').startswith('handle_query_with_state')
    ]
    assert len(search_events) == 2
    assert all(profile['id'] in dependency['outputs'] for dependency in search_events)
