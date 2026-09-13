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
    })
    monkeypatch.setattr(app, 'run_agent', runner)
    listing, outfit, card = app.handle_query('vintage jeans', choice)
    runner.assert_called_once()
    assert runner.call_args.kwargs['query'] == 'vintage jeans'
    wardrobe = runner.call_args.kwargs['wardrobe']
    assert bool(wardrobe['items']) == (choice == 'Example wardrobe')
    assert item['title'] in listing
    assert f"${item['price']:.2f}" in listing
    assert item['platform'] in listing
    assert (outfit, card) == ('Exact outfit.', 'Exact caption.')


def test_error_clears_other_panels(monkeypatch):
    monkeypatch.setattr(app, 'run_agent', Mock(return_value={'error': 'No matching listings.'}))
    assert app.handle_query('ballgown', 'Example wardrobe') == ('No matching listings.', '', '')
