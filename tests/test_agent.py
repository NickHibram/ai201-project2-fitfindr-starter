from unittest.mock import Mock, patch

import pytest

import agent
from utils.data_loader import get_example_wardrobe, load_listings


EXAMPLE_QUERY = (
    "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans "
    "and chunky sneakers. What's out there and how would I style it?"
)


@pytest.fixture
def tool_mocks(monkeypatch):
    mocks = {
        'search_listings': Mock(return_value=load_listings()[:2]),
        'suggest_outfit': Mock(return_value='  Tee with jeans and sneakers.  '),
        'create_fit_card': Mock(return_value='A shareable fit card.'),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(agent, name, mock)
    return mocks


def test_success_passes_exact_state(tool_mocks):
    wardrobe = get_example_wardrobe()
    session = agent.run_agent(EXAMPLE_QUERY, wardrobe)
    search, suggest, card = (tool_mocks[name] for name in tool_mocks)
    assert session['error'] is None
    assert session['query'] == EXAMPLE_QUERY
    assert session['wardrobe'] is wardrobe
    assert session['parsed'] == {'description': 'vintage graphic tee', 'size': None, 'max_price': 30.0}
    search.assert_called_once_with(**session['parsed'])
    assert session['search_results'] is search.return_value
    assert session['selected_item'] is search.return_value[0]
    suggest.assert_called_once()
    assert suggest.call_args.kwargs['new_item'] is session['selected_item']
    assert suggest.call_args.kwargs['wardrobe'] is wardrobe
    assert session['outfit_suggestion'] is suggest.return_value
    card.assert_called_once()
    assert card.call_args.kwargs['outfit'] is session['outfit_suggestion']
    assert card.call_args.kwargs['new_item'] is session['selected_item']
    assert session['fit_card'] is card.return_value


def test_empty_search_stops_both_later_tools(tool_mocks):
    tool_mocks['search_listings'].return_value = []
    session = agent.run_agent('designer ballgown size XXS under $5', {'items': []})
    assert session['error'] is not None
    assert session['selected_item'] is None
    assert session['outfit_suggestion'] is None
    assert session['fit_card'] is None
    tool_mocks['search_listings'].assert_called_once_with(
        description='designer ballgown', size='XXS', max_price=5.0,
    )
    tool_mocks['suggest_outfit'].assert_not_called()
    tool_mocks['create_fit_card'].assert_not_called()


@pytest.mark.parametrize(('query', 'description', 'size', 'price'), [
    ('vintage graphic tee under $30', 'vintage graphic tee', None, 30.0),
    ('90s track jacket in size M', '90s track jacket', 'M', None),
    ('flowy midi skirt under $40', 'flowy midi skirt', None, 40.0),
    ('black combat boots size 8', 'black combat boots', '8', None),
    ('boots size US 8.5 up to $30.50', 'boots', 'US 8.5', 30.5),
    ('jeans size W30 L30 max price 40', 'jeans', 'W30 L30', 40.0),
    ('tee size s/m below 25', 'tee', 'S/M', 25.0),
])
def test_query_parsing(query, description, size, price):
    assert agent._parse_query(query) == {
        'description': description, 'size': size, 'max_price': price,
    }


@pytest.mark.parametrize('query', ['', '   ', 'size M under $30'])
def test_missing_description_calls_no_tools(tool_mocks, query):
    session = agent.run_agent(query, {'items': []})
    assert session['error']
    assert session['fit_card'] is None
    for mock in tool_mocks.values():
        mock.assert_not_called()


@pytest.mark.parametrize('value', [None, '', ' \n '])
@pytest.mark.parametrize('name', ['suggest_outfit', 'create_fit_card'])
def test_empty_generated_output_stops(tool_mocks, name, value):
    tool_mocks[name].return_value = value
    session = agent.run_agent('tee', {'items': []})
    assert session['error']
    assert session['outfit_suggestion'] is None
    assert session['fit_card'] is None
    if name == 'suggest_outfit':
        tool_mocks['create_fit_card'].assert_not_called()


@pytest.mark.parametrize('name', ['search_listings', 'suggest_outfit', 'create_fit_card'])
def test_tool_exceptions_return_error_session(tool_mocks, name):
    tool_mocks[name].side_effect = ValueError('private provider details')
    session = agent.run_agent('tee', {'items': []})
    assert session['error']
    assert 'private provider details' not in session['error']
    assert session['outfit_suggestion'] is None
    assert session['fit_card'] is None
    if name == 'search_listings':
        tool_mocks['suggest_outfit'].assert_not_called()
    if name != 'create_fit_card':
        tool_mocks['create_fit_card'].assert_not_called()


def test_real_search_branch_and_session_isolation():
    with patch.object(agent, 'suggest_outfit', return_value='Styling advice.') as suggest, \
         patch.object(agent, 'create_fit_card', return_value='Caption.') as card:
        success = agent.run_agent(EXAMPLE_QUERY, {'items': []})
        assert success['error'] is None
        assert success['selected_item'] is success['search_results'][0]
        assert success['selected_item']['price'] <= 30
        assert suggest.call_args.kwargs['wardrobe'] == {'items': []}
        failure = agent.run_agent('designer ballgown size XXS under $5', {'items': []})
        assert failure['error'] is not None
        assert failure['fit_card'] is None
        assert success['fit_card'] == 'Caption.'
        # Only the successful run may call the LLM tools.
        suggest.assert_called_once()
        card.assert_called_once()
