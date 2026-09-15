import json
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


@pytest.mark.parametrize(('price', 'label'), [
    (17, 'Good Deal'), (18, 'Fair Price'), (20, 'Fair Price'),
    (22, 'Fair Price'), (23, 'Bad Deal'),
])
def test_compare_price_labels_and_boundaries(monkeypatch, item, price, label):
    selected = dict(item, price=price)
    monkeypatch.setattr(tools, 'load_listings', lambda: [
        selected, dict(item, id='other1', price=18), dict(item, id='other2', price=22),
        dict(item, id='unrelated', title='Vintage Hoodie', style_tags=['vintage'], price=200),
    ])
    result = tools.compare_price(selected)
    assert result.startswith(f'### {label}\n')
    assert '$20.00 median' in result
    assert '2 comparable listings' in result
    assert '$18.00 to $22.00' in result
    assert 'Vintage Hoodie' not in result


def test_compare_price_real_dataset():
    selected = next(item for item in load_listings() if item['id'] == 'lst_002')
    result = tools.compare_price(selected)
    assert result.startswith('### Good Deal')
    assert '$24.00 median' in result
    assert '25.0% below' in result


@pytest.mark.parametrize(('description', 'size'), [
    ('vintage graphic tee', 'S'), ('vintage graphic tee', 'M'),
    ('vintage graphic tee', 'L'), ('vintage graphic tee', 'XL'),
    ('vintage flannel shirt', 'L'), ('vintage flannel shirt', 'M'),
    ('90s track jacket', 'M'), ('90s track jacket', 'L'),
    ('vintage baggy jeans', 'W30'), ('vintage baggy jeans', 'W32'),
    ('chunky sneakers', 'US 8'), ('chunky sneakers', 'US 9'),
    ('black combat boots', 'US 8'), ('vintage linen blazer', 'M'),
])
def test_dataset_supports_size_filtered_comparisons(description, size):
    results = tools.search_listings(description, size=size)
    assert len(results) >= 3
    assessment = tools.compare_price(results[0], {'description': description, 'size': size})
    assert assessment.startswith('### ')
    assert 'comparable listings' in assessment
    assert 'Insufficient comparison data' not in assessment


def test_comparison_examples_cover_all_price_labels():
    records = {record['id']: record for record in load_listings()}
    for listing_id, label in [('lst_059', 'Good Deal'), ('lst_060', 'Fair Price'), ('lst_061', 'Bad Deal')]:
        assessment = tools.compare_price(records[listing_id], {'description': '90s track jacket', 'size': 'M'})
        assert assessment.startswith(f'### {label}\n')


def test_listings_have_unique_ids_and_complete_fields():
    records = load_listings()
    assert len({record['id'] for record in records}) == len(records)
    required = {'id', 'title', 'description', 'category', 'style_tags', 'size', 'condition', 'price', 'colors', 'brand', 'platform'}
    for record in records:
        assert required <= record.keys()
        assert isinstance(record['price'], (int, float)) and record['price'] > 0
        assert record['style_tags'] and record['colors']


def test_comparison_respects_search_size_and_ranks_description(monkeypatch, item):
    records = [
        item,
        dict(item, id='a', title='Plain Tee', description='', style_tags=[], size='L', price=20),
        dict(item, id='b', title='Graphic Tee', size='L/XL', price=60),
        dict(item, id='c', title='Small Graphic Tee', size='S', price=1),
        dict(item, id='d', title='XL Graphic Tee', size='XL', price=2),
    ]
    monkeypatch.setattr(tools, 'load_listings', lambda: records)
    result = tools.compare_price(item, {'description': 'graphic tee', 'size': 'large', 'max_price': 30})
    assert '$40.00 median' in result
    assert '2 comparable listings' in result
    assert '| Graphic Tee |' in result and '| Plain Tee |' in result
    assert result.index('| Graphic Tee |') < result.index('| Plain Tee |')
    assert 'Small Graphic Tee' not in result and 'XL Graphic Tee' not in result
    assert 'Requested size: L' in result
    assert 'budget is not applied' in result


def test_comparison_does_not_relax_size_for_insufficient_matches(monkeypatch, item):
    monkeypatch.setattr(tools, 'load_listings', lambda: [
        item, dict(item, id='a', size='L'), dict(item, id='b', size='S'),
    ])
    result = tools.compare_price(item, {'description': 'tee', 'size': 'L'})
    assert 'Insufficient comparison data' in result and 'found 1 other' in result
    assert 'Requested size: L' in result


def test_search_accepts_size_words(monkeypatch, item):
    monkeypatch.setattr(tools, 'load_listings', lambda: [item, dict(item, id='xl', size='XL')])
    assert tools.search_listings('tee', size='large') == [item]


def test_compare_price_missing_selection(groq_mock):
    constructor, _ = groq_mock
    assert 'search for an item first' in tools.compare_price(None)
    constructor.assert_not_called()


def test_compare_price_insufficient_data(monkeypatch, item):
    monkeypatch.setattr(tools, 'load_listings', lambda: [item, dict(item, id='other')])
    result = tools.compare_price(item)
    assert 'Insufficient comparison data' in result
    assert 'found 1 other' in result


def test_compare_price_reacts_to_dataset_prices(monkeypatch, item, groq_mock):
    _, client = groq_mock
    records = [dict(item, id='a', price=10), dict(item, id='b', price=20)]
    monkeypatch.setattr(tools, 'load_listings', lambda: records)
    assert '### Bad Deal' in tools.compare_price(item)
    records[0]['price'] = 40
    records[1]['price'] = 60
    assert '### Good Deal' in tools.compare_price(item)
    client.chat.completions.create.assert_not_called()


def test_compare_price_requires_same_category(monkeypatch, item):
    monkeypatch.setattr(tools, 'load_listings', lambda: [
        dict(item, id='a', category='outerwear'), dict(item, id='b', category='outerwear'),
    ])
    assert 'Insufficient comparison data' in tools.compare_price(item)


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


def test_suggest_outfit_includes_prior_style_memory(item, groq_mock):
    _, client = groq_mock
    memory = (
        '# Style Profile Memory\n\n'
        'Preferences: vintage, streetwear, relaxed\n\n'
        'Previous outfit: Baggy jeans and chunky sneakers.'
    )

    assert tools.suggest_outfit(item, {'items': []}, style_memory=memory) == 'Styling result.'

    messages = client.chat.completions.create.call_args.kwargs['messages']
    assert json.loads(messages[1]['content'])['style_memory'] == memory
    assert 'previously learned style preferences' in messages[0]['content'].lower()


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
