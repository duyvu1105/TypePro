import pytest
from type_labels import normalize_type_label


@pytest.mark.parametrize('raw, expected', [
    ('List <eol> str <eol> <eot>', 'List[str]'),
    ('Dict <eol> str <kvsep> Dict <eol> <typesep> str <kvsep> str <eol> <eot>', 'Dict[str, Dict[str, str]]'),
    ('Tuple <eol> Any Tuple <eol> <typesep> Any str <eol> <eot>', 'Tuple[Any, Tuple[Any, str]]'),
    ('Callable <eol> str <kvsep> bool <eol> <eot>', 'Callable[[str], bool]'),
    ('Callable <eol>  <kvsep> None <eol> <eot>', 'Callable[[], None]'),
    ('dict <eot>', 'dict'), ('none', 'None'),
    (' Dict[str,Any] ', 'Dict[str, Any]'),
])
def test_python_form(raw, expected):
    assert normalize_type_label(raw) == expected
    assert normalize_type_label(expected) == expected


@pytest.mark.parametrize('raw', ['List <eol> str', 'List[Broken', 'Callable <eol> str <kvsep> <eol> <eot>'])
def test_invalid_types_fail(raw):
    with pytest.raises(ValueError):
        normalize_type_label(raw)
