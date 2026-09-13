from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import httpx
from groq import APIConnectionError

import tools
from utils.data_loader import get_example_wardrobe, load_listings


@pytest.fixture
def item():
    return next(item for item in load_listings() if item['id'] == 'lst_006')


@pytest.fixture
def groq_mock(monkeypatch):
    # Patch the constructor so no unit test can contact the live service.
    constructor = Mock()
    monkeypatch.setattr(tools, 'Groq', constructor)
    monkeypatch.setenv('GROQ_API_KEY', 'unit-test-key')
    client = constructor.return_value
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='  Styling result.  '))]
    )
    return constructor, client


def test_search_real_dataset():
    results = tools.search_listings('vintage graphic tee', size=None, max_price=30)
    assert results
    assert any(item['id'] == 'lst_006' for item in results)


@pytest.mark.parametrize('description', ['xyzzyunfindable', '', '   ', '!!!'])
def test_search_no_matches(description):
    assert tools.search_listings(description) == []


def test_search_price_is_inclusive():
    results = tools.search_listings('graphic tee', max_price=24)
    assert results
    assert all(item['price'] <= 24 for item in results)
    assert any(item['id'] == 'lst_006' for item in results)
    assert tools.search_listings('graphic tee', max_price=0) == []


def test_search_none_filters():
    results = tools.search_listings('vintage', size=None, max_price=None)
    assert len({item['size'] for item in results}) > 1
    assert any(item['price'] > 30 for item in results)


def test_search_ranking_and_original_records(monkeypatch, item):
    listings = [
        dict(item, id='weak', title='Tee', description='', style_tags=[], colors=[], brand=None),
        dict(item, id='strong', title='VINTAGE Graphic-Tee!', description='', style_tags=[], colors=[], brand=None),
        dict(item, id='none', title='Trousers', description='', style_tags=[], colors=[], brand=None),
    ]
    loader = Mock(return_value=listings)
    monkeypatch.setattr(tools, 'load_listings', loader)
    results = tools.search_listings('vintage graphic tee')
    loader.assert_called_once_with()
    assert [result['id'] for result in results] == ['strong', 'weak']
    assert results[0] is listings[1]
    assert 'score' not in results[0]


@pytest.mark.parametrize(('size', 'expected'), [
    ('m', ['M', 'S/M']), (' L ', ['L', 'L/XL']),
    ('8', ['US 8']), ('W30', ['W30 L30']),
])
def test_search_size_boundaries(monkeypatch, item, size, expected):
    sizes = ['M', 'S/M', 'L', 'L/XL', 'XL', 'US 8', 'US 8.5', 'W30 L30']
    monkeypatch.setattr(tools, 'load_listings', lambda: [dict(item, size=s) for s in sizes])
    assert [result['size'] for result in tools.search_listings('tee', size=size)] == expected


def test_suggest_outfit_with_wardrobe(item, groq_mock):
    constructor, client = groq_mock
    wardrobe = get_example_wardrobe()
    assert tools.suggest_outfit(item, wardrobe) == 'Styling result.'
    assert constructor.call_args.kwargs['api_key'] == 'unit-test-key'
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs['model'] == 'openai/gpt-oss-120b'
    prompt = str(kwargs['messages'])
    assert item['title'] in prompt
    assert all(piece['name'] in prompt for piece in wardrobe['items'])


def test_suggest_outfit_empty_wardrobe(item, groq_mock):
    _, client = groq_mock
    assert tools.suggest_outfit(item, {'items': []}) == 'Styling result.'
    client.chat.completions.create.assert_called_once()
    prompt = str(client.chat.completions.create.call_args.kwargs['messages']).lower()
    assert 'general styling advice' in prompt
    assert 'empty' in prompt
    assert item['title'].lower() in prompt


@pytest.mark.parametrize('outfit', ['', '   ', '\n\t', None])
def test_fit_card_empty_outfit_does_not_call_groq(item, groq_mock, outfit):
    constructor, _ = groq_mock
    result = tools.create_fit_card(outfit, item)
    assert 'without an outfit suggestion' in result.lower()
    constructor.assert_not_called()


def test_fit_card_valid(item, groq_mock):
    _, client = groq_mock
    outfit = 'Graphic tee with baggy jeans and chunky white sneakers.'
    assert tools.create_fit_card(outfit, item) == 'Styling result.'
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs['model'] == 'openai/gpt-oss-120b'
    assert 0 < kwargs['temperature'] <= 2
    prompt = str(kwargs['messages'])
    for detail in (outfit, item['title'], str(item['price']), item['platform']):
        assert detail in prompt
    assert 'once each' in prompt
    assert '2–4' in prompt


@pytest.mark.parametrize('function', ['suggest_outfit', 'create_fit_card'])
@pytest.mark.parametrize('content', [None, '', '  '])
def test_empty_llm_response_is_explicit_error(item, groq_mock, function, content):
    _, client = groq_mock
    client.chat.completions.create.return_value.choices[0].message.content = content
    args = (item, {'items': []}) if function == 'suggest_outfit' else ('A complete outfit.', item)
    with pytest.raises(ValueError, match='empty response'):
        getattr(tools, function)(*args)


def test_missing_key_is_explicit_error(monkeypatch, groq_mock):
    constructor, _ = groq_mock
    monkeypatch.delenv('GROQ_API_KEY')
    with pytest.raises(ValueError, match='GROQ_API_KEY not set'):
        tools._get_groq_client()
    constructor.assert_not_called()


def test_fit_card_calls_are_not_cached(item, groq_mock):
    _, client = groq_mock
    for _ in range(3):
        tools.create_fit_card('Tee, jeans, and sneakers.', item)
    assert client.chat.completions.create.call_count == 3


@pytest.mark.parametrize('function', ['suggest_outfit', 'create_fit_card'])
def test_no_llm_choices_is_explicit_error(item, groq_mock, function):
    _, client = groq_mock
    client.chat.completions.create.return_value.choices = []
    args = (item, {'items': []}) if function == 'suggest_outfit' else ('A complete outfit.', item)
    with pytest.raises(ValueError, match='empty response'):
        getattr(tools, function)(*args)


@pytest.mark.parametrize('function', ['suggest_outfit', 'create_fit_card'])
def test_api_errors_propagate_to_planning_loop(item, groq_mock, function):
    _, client = groq_mock
    error = APIConnectionError(request=httpx.Request('POST', 'https://api.groq.com'))
    client.chat.completions.create.side_effect = error
    args = (item, {'items': []}) if function == 'suggest_outfit' else ('A complete outfit.', item)
    with pytest.raises(APIConnectionError) as caught:
        getattr(tools, function)(*args)
    assert caught.value is error
