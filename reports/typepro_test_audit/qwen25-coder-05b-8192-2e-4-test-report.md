# Báo cáo dự đoán kiểu dữ liệu trên tập test v15 đã làm sạch

## Phạm vi và cách tính

- Tập test: `datasets/typepro-python-generative-v15/test.jsonl`.
- Kết quả model: `outputs/qwen25-coder-05b-8192/test_predictions.jsonl`.
- Số mẫu: **3,277**; số nhãn kiểu dữ liệu khác nhau: **434**.
- Hai file được ghép theo `id`; không có ID trùng, thiếu hoặc dư.
- Một dự đoán đúng khi `exact_match=true`, tức `normalized_prediction` bằng nhãn đã chuẩn hóa.

## Kiểm tra dữ liệu recommendation đã làm sạch

Mỗi mẫu v15 chứa 10 recommendation. Việc khử trùng dùng `qualified_name` làm khóa: alias cùng định danh bị loại, còn các type trùng tên nhưng thuộc module/package khác vẫn là các ứng viên riêng.

- Số `qualified_name` trùng trong cùng một mẫu: **0**.
- 20 ví dụ bên dưới được chọn từ v15 và không có cặp `[TYPE]`/`[DEFINITION]` trùng nhau trong block hiển thị.
- ID có thể khác report cũ vì v15 được dựng lại từ dữ liệu đã làm sạch.

## Kết quả tổng quan

| Chỉ số | Đúng | Tổng | Tỷ lệ |
| --- | ---: | ---: | ---: |
| Exact match sau chuẩn hóa | 2,775 | 3,277 | 84.68% |
| Exact match chuỗi thô | 2,775 | 3,277 | 84.68% |
| Sai sau chuẩn hóa | 502 | 3,277 | 15.32% |

Có **3** dự đoán không chuẩn hóa được và **1** dự đoán rỗng. Bước chuẩn hóa làm tăng đúng **0** mẫu so với so sánh chuỗi thô.

### Theo vị trí cần dự đoán

| Phạm vi | Đúng | Tổng | Tỷ lệ đúng |
| --- | ---: | ---: | ---: |
| `arg` | 1,891 | 2,182 | 86.66% |
| `return` | 884 | 1,095 | 80.73% |

## 5 ví dụ dự đoán đúng

### Đúng 1: `is_scalar` → `bool`

- ID: `opethe1st/MyJson:repos/opethe1st/MyJson/src/myjson/loading/node_from_tokens.py:43756:is_scalar`
- Project: `opethe1st/MyJson`
- Hàm đích: `is_scalar`
- Phạm vi: `return`
- Nhãn: `bool`
- Dự đoán thô: `bool`
- Dự đoán chuẩn hóa: `bool`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] is_scalar
[TARGET_FUNCTION] is_scalar
[TARGET_SCOPE] return
[INTERPROCEDURAL_SLICE]
from enum import Enum
from typing import List, Tuple
from myjson.core import MappingNode, Node, ScalarNode, SequenceNode
from .tokenization import (
    Delimiter,
    MappingEnd,
    MappingStart,
    ScalarValue,
    Separator,
    SequenceEnd,
    SequenceStart,
    Token,
    tokenize
)
def is_scalar(tokens: List['Token'], start: int) -> <mask>:
    if start < len(tokens):
        return isinstance(tokens[start], ScalarValue)
    else:
        return False
function mapping_node_from_tokens(tokens: List['Token'], start: int) -> Tuple['MappingNode', int]
function sequence_node_from_tokens(tokens: List['Token'], start: int) -> Tuple['SequenceNode', int]
function scalar_node_from_tokens(tokens: List['Token'], start: int) -> Tuple['ScalarNode', int]
is_scalar(tokens=tokens, start=start)
return mapping_node_from_tokens(tokens=tokens, start=start)
return sequence_node_from_tokens(tokens=tokens, start=start)
return scalar_node_from_tokens(tokens=tokens, start=start)
return isinstance(tokens[start], MappingStart)
keyNode = scalar_node_from_tokens(tokens=tokens, start=currentPosition)[0]
lastPosition = scalar_node_from_tokens(tokens=tokens, start=currentPosition)[1]
valueNode = node_from_tokens(tokens=tokens, start=lastPosition + 1)[0]
lastPosition = node_from_tokens(tokens=tokens, start=lastPosition + 1)[1]
return isinstance(tokens[start], SequenceStart)
valueNode = node_from_tokens(tokens=tokens, start=currentPosition)[0]
lastPosition = node_from_tokens(tokens=tokens, start=currentPosition)[1]
return isinstance(tokens[start], ScalarValue)
return (ScalarNode(data=tokens[start].data), start + 1)
currentPosition = start + 1
is_scalar(tokens=[ScalarValue(data='value')], start=0)
[RECOMMENDATION_TYPES]
[TYPE] MappingNode
[DEFINITION]
class MappingNode(Node):
    mapping: typing.Dict['ScalarNode', 'Node']
[TYPE] SequenceNode
[DEFINITION]
class SequenceNode(Node):
    items: typing.List['Node']
[TYPE] ScalarNode
[DEFINITION]
class ScalarNode(Node):
    data: str
[TYPE] ScalarValue
[DEFINITION]
class ScalarValue(Token):
    data: str
[TYPE] Delimiter
[DEFINITION]
class Delimiter(Token):
    pass
[TYPE] MappingEnd
[DEFINITION]
class MappingEnd(Token):
    pass
[TYPE] MappingStart
[DEFINITION]
class MappingStart(Token):
    pass
[TYPE] Separator
[DEFINITION]
class Separator(Token):
    pass
[TYPE] SequenceEnd
[DEFINITION]
class SequenceEnd(Token):
    pass
[TYPE] SequenceStart
[DEFINITION]
class SequenceStart(Token):
    pass
```

### Đúng 2: `state` → `str`

- ID: `kelsos/test-environment-scripts:repos/kelsos/test-environment-scripts/raiden_api/model/data.py:35181:state`
- Project: `kelsos/test-environment-scripts`
- Hàm đích: `Channel.__init__`
- Phạm vi: `arg`
- Nhãn: `str`
- Dự đoán thô: `str`
- Dự đoán chuẩn hóa: `str`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] state
[TARGET_FUNCTION] Channel.__init__
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
import typing
def __init__(self, token_network_identifier: str, channel_identifier: int, partner_address: str, token_address: str, balance: int, total_deposit: int, state: <mask>, settle_timeout: int, reveal_timeout: int):
    self.token_network_identifier = token_network_identifier
    self.channel_identifier = channel_identifier
    self.partner_address = partner_address
    self.token_address = token_address
    self.balance = balance
    self.total_deposit = total_deposit
    self.state = state
    self.settle_timeout = settle_timeout
    self.reveal_timeout = reveal_timeout
[RECOMMENDATION_TYPES]
[TYPE] AbstractSet
[DEFINITION]
class AbstractSet(Collection[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def isdisjoint(self, other: Iterable[Any], /) -> bool:
[TYPE] Iterator
[DEFINITION]
@runtime_checkable
class Iterator(Iterable[_T_co], Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] Hashable
[DEFINITION]
@runtime_checkable
class Hashable(Protocol, metaclass=ABCMeta):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] AsyncIterator
[DEFINITION]
@runtime_checkable
class AsyncIterator(AsyncIterable[_T_co], Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] SupportsBytes
[DEFINITION]
@runtime_checkable
class SupportsBytes(Protocol, metaclass=ABCMeta):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] SupportsFloat
[DEFINITION]
@runtime_checkable
class SupportsFloat(Protocol, metaclass=ABCMeta):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] Awaitable
[DEFINITION]
@runtime_checkable
class Awaitable(Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] MutableSet
[DEFINITION]
class MutableSet(AbstractSet[_T]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def add(self, value: _T, /) -> None:
    def discard(self, value: _T, /) -> None:
    def clear(self) -> None:
    def pop(self) -> _T:
    def remove(self, value: _T, /) -> None:
[TYPE] Sized
[DEFINITION]
@runtime_checkable
class Sized(Protocol, metaclass=ABCMeta):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __len__(self) -> int:
[TYPE] Container
[DEFINITION]
@runtime_checkable
class Container(Protocol[_ContainerT_contra]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
```

### Đúng 3: `nums` → `List[int]`

- ID: `shunkakinoki/leetcode:repos/shunkakinoki/leetcode/src/1.two-sum.py:49976:nums`
- Project: `shunkakinoki/leetcode`
- Hàm đích: `Solution.twoSum`
- Phạm vi: `arg`
- Nhãn: `List[int]`
- Dự đoán thô: `List[int]`
- Dự đoán chuẩn hóa: `List[int]`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] nums
[TARGET_FUNCTION] Solution.twoSum
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from typing import List, Optional, Tuple
def twoSum(self, nums: <mask>, target: int) -> Optional[List[int]]:
    nums_index: List[Tuple[int, int]] = [(v, index) for index, v in enumerate(nums)]
    nums_index.sort()
    begin: int = 0
    end: int = len(nums) - 1
    while begin < end:
        current = nums_index[begin][0] + nums_index[end][0]
        if current == target:
            return [nums_index[begin][1], nums_index[end][1]]
        elif current < target:
            begin += 1
        else:
            end -= 1
    return None
s.twoSum([2, 7, 11, 15], 9)
[RECOMMENDATION_TYPES]
[TYPE] ItemsView
[DEFINITION]
class ItemsView(MappingView, AbstractSet[tuple[_KT_co, _VT_co]], Generic[_KT_co, _VT_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __init__(self, mapping: SupportsGetItemViewable[_KT_co, _VT_co]) -> None:
    def __iter__(self) -> Iterator[tuple[_KT_co, _VT_co]]:
[TYPE] _S
[DEFINITION]
class _S:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('_S')
[TYPE] AnyStr
[DEFINITION]
class AnyStr:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('AnyStr', str, bytes)
[TYPE] ParamSpec
[DEFINITION]
@final
class ParamSpec:
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def args(self) -> ParamSpecArgs:
    def kwargs(self) -> ParamSpecKwargs:
[TYPE] MutableSet
[DEFINITION]
class MutableSet(AbstractSet[_T]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def add(self, value: _T, /) -> None:
    def discard(self, value: _T, /) -> None:
    def clear(self) -> None:
    def pop(self) -> _T:
    def remove(self, value: _T, /) -> None:
[TYPE] NamedTuple
[DEFINITION]
class NamedTuple(tuple[Any, ...]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __init__(self, typename: str, fields: Iterable[tuple[str, Any]], /) -> None:
    def __init__(self, typename: str, fields: None=None, /, **kwargs: Any) -> None:
[TYPE] Any
[DEFINITION]
class Any:
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] ValuesView
[DEFINITION]
class ValuesView(MappingView, Collection[_VT_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __init__(self, mapping: SupportsGetItemViewable[Any, _VT_co]) -> None:
    def __iter__(self) -> Iterator[_VT_co]:
[TYPE] SupportsAbs
[DEFINITION]
@runtime_checkable
class SupportsAbs(Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] ParamSpecArgs
[DEFINITION]
@final
class ParamSpecArgs:
    # package: typing
    # module: typing
    # source: typeshed
    pass
```

### Đúng 4: `user_mapping` → `Dict[str, User]`

- ID: `jwnwilson/python_types:repos/jwnwilson/python_types/main.py:34778:user_mapping`
- Project: `jwnwilson/python_types`
- Hàm đích: `expect_user_mapping`
- Phạm vi: `arg`
- Nhãn: `Dict[str, User]`
- Dự đoán thô: `Dict[str, User]`
- Dự đoán chuẩn hóa: `Dict[str, User]`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] user_mapping
[TARGET_FUNCTION] expect_user_mapping
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from typing import List
from typing import Mapping
from typing import Sequence
def expect_user_mapping(user_mapping: <mask>) -> None:
    """Take a mapping of string -> users

    :param user_mapping: [description]
    """
    for key in user_mapping:
        print(f'User: {user_mapping[key]}')
expect_user_mapping({'test': User()})
[RECOMMENDATION_TYPES]
[TYPE] Mapping
[DEFINITION]
class Mapping(Collection[_KT], Generic[_KT, _VT_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, key: _KT, /) -> _VT_co:
    def get(self, key: _KT, /) -> _VT_co | None:
    def get(self, key: _KT, default: _VT_co, /) -> _VT_co:
    def get(self, key: _KT, default: _T, /) -> _VT_co | _T:
    def items(self) -> ItemsView[_KT, _VT_co]:
    def keys(self) -> KeysView[_KT]:
    def values(self) -> ValuesView[_VT_co]:
[TYPE] Sequence
[DEFINITION]
class Sequence(Reversible[_T_co], Collection[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, index: int, /) -> _T_co:
    def __getitem__(self, index: slice[int | None], /) -> Sequence[_T_co]:
    def index(self, value: Any, start: int=0, stop: int=..., /) -> int:
    def count(self, value: Any, /) -> int:
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] User
[DEFINITION]
class User:
    def __str__(self):
        return 'User instance!'
[TYPE] MutableMapping
[DEFINITION]
class MutableMapping(Mapping[_KT, _VT]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def clear(self) -> None:
    def pop(self, key: _KT, /) -> _VT:
    def pop(self, key: _KT, default: _VT, /) -> _VT:
    def pop(self, key: _KT, default: _T, /) -> _VT | _T:
    def popitem(self) -> tuple[_KT, _VT]:
    def setdefault(self: MutableMapping[_KT, _T | None], key: _KT, default: None=None, /) -> _T | None:
    def setdefault(self, key: _KT, default: _VT, /) -> _VT:
    def update(self, m: SupportsKeysAndGetItem[_KT, _VT], /) -> None:
    def update(self: SupportsGetItem[str, _VT], m: SupportsKeysAndGetItem[str, _VT], /, **kwargs: _VT) -> None:
    def update(self, m: Iterable[tuple[_KT, _VT]], /) -> None:
    def update(self: SupportsGetItem[str, _VT], m: Iterable[tuple[str, _VT]], /, **kwargs: _VT) -> None:
    def update(self: SupportsGetItem[str, _VT], /, **kwargs: _VT) -> None:
[TYPE] _P
[DEFINITION]
class _P:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: ParamSpec('_P')
[TYPE] MappingView
[DEFINITION]
class MappingView(Sized):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __init__(self, mapping: Sized) -> None:
    def __len__(self) -> int:
[TYPE] _S
[DEFINITION]
class _S:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('_S')
[TYPE] ByteString
[DEFINITION]
class ByteString:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: bytes | bytearray | memoryview
[TYPE] SupportsInt
[DEFINITION]
@runtime_checkable
class SupportsInt(Protocol, metaclass=ABCMeta):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] _SendT_contra
[DEFINITION]
class _SendT_contra:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('_SendT_contra', contravariant=True, default=None)
```

### Đúng 5: `keys` → `List[str]`

- ID: `RacingTadpole/python-workshop:repos/RacingTadpole/python-workshop/python_workshop/types/t01_functions.py:9050:keys`
- Project: `RacingTadpole/python-workshop`
- Hàm đích: `splice`
- Phạm vi: `arg`
- Nhãn: `List[str]`
- Dự đoán thô: `List[str]`
- Dự đoán chuẩn hóa: `List[str]`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] keys
[TARGET_FUNCTION] splice
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from typing import List, Dict
def splice(keys: <mask>, values: List[int]) -> Dict[str, int]:
    return {k: v for k, v in zip(keys, values)}
[RECOMMENDATION_TYPES]
[TYPE] List
[DEFINITION]
class List(list, Static):
    # package: setuptools
    # module: setuptools._static
    # source: third_party
    pass
[TYPE] Dict
[DEFINITION]
class Dict(dict, Static):
    # package: setuptools
    # module: setuptools._static
    # source: third_party
    pass
[TYPE] _TypedDict
[DEFINITION]
@type_check_only
class _TypedDict(Mapping[str, object], metaclass=ABCMeta):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def copy(self) -> typing_extensions.Self:
    def setdefault(self, k: _Never, default: object) -> object:
    def pop(self, k: _Never, default: _T=...) -> object:
    def update(self, m: typing_extensions.Self, /) -> None:
    def items(self) -> dict_items[str, object]:
    def keys(self) -> dict_keys[str, object]:
    def values(self) -> dict_values[str, object]:
[TYPE] Mapping
[DEFINITION]
class Mapping(Collection[_KT], Generic[_KT, _VT_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, key: _KT, /) -> _VT_co:
    def get(self, key: _KT, /) -> _VT_co | None:
    def get(self, key: _KT, default: _VT_co, /) -> _VT_co:
    def get(self, key: _KT, default: _T, /) -> _VT_co | _T:
    def items(self) -> ItemsView[_KT, _VT_co]:
    def keys(self) -> KeysView[_KT]:
    def values(self) -> ValuesView[_VT_co]:
[TYPE] InventoryItem
[DEFINITION]
class InventoryItem:
    name: str
    unit_price: float
    quantity_on_hand: int = 0

    @property
    def total_cost(self) -> float:
        """
        Note the docstring tests.
        These are run automatically in pytest, with the right pytest.ini.
        Unfortunately mypy doesn't type check them though :-(

        >>> item = InventoryItem(name='rice', unit_price=2.5, quantity_on_hand=3)
        >>> item.total_cost
        7.5
        >>> InventoryItem(name='beans', unit_price=1.5).quantity_on_hand
        0
        """
        return self.unit_price * self.quantity_on_hand
[TYPE] NamedSequence
[DEFINITION]
class NamedSequence(Generic[T]):
    """
    You can provide alternative type signatures for a function.
    A good example where you need this is __getitem__, which allows for both x[1] and x[1:3].
    """
    name: str
    values: Sequence[T]

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[T]: ...

    def __getitem__(self, index: Union[int, slice]) -> Union[T, Sequence[T]]:
        """
        >>> x = NamedSequence(name='foo', values=(5, 10, 25, 100))
        >>> x[1]
        10
        >>> x[1:3]
        (10, 25)
        >>> x[1:]
        (10, 25, 100)
        """
        return self.values[index]
[TYPE] Stack
[DEFINITION]
class Stack(Generic[T]):
    def __init__(self) -> None:
        # Create an empty list with items of type T
        self.items: List[T] = []

    def push(self, item: T) -> None:
        self.items.append(item)

    def pop(self) -> T:
        return self.items.pop()

    def empty(self) -> bool:
        return not self.items
[TYPE] KeysView
[DEFINITION]
class KeysView(MappingView, AbstractSet[_KT_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __init__(self, mapping: Viewable[_KT_co]) -> None:
    def __iter__(self) -> Iterator[_KT_co]:
[TYPE] _S
[DEFINITION]
class _S:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('_S')
[TYPE] AnyStr
[DEFINITION]
class AnyStr:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('AnyStr', str, bytes)
```


## 5 ví dụ dự đoán sai

### Sai 1: nhãn `List['Token']`, model dự đoán `List[Token]`

- ID: `opethe1st/MyJson:repos/opethe1st/MyJson/src/myjson/loading/node_from_tokens.py:43755:tokens`
- Project: `opethe1st/MyJson`
- Hàm đích: `is_scalar`
- Phạm vi: `arg`
- Nhãn: `List['Token']`
- Dự đoán thô: `List[Token]`
- Dự đoán chuẩn hóa: `List[Token]`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] tokens
[TARGET_FUNCTION] is_scalar
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from enum import Enum
from typing import List, Tuple
from myjson.core import MappingNode, Node, ScalarNode, SequenceNode
from .tokenization import (
    Delimiter,
    MappingEnd,
    MappingStart,
    ScalarValue,
    Separator,
    SequenceEnd,
    SequenceStart,
    Token,
    tokenize
)
@dataclass
class Token:
def is_scalar(tokens: <mask>, start: int) -> bool:
    if start < len(tokens):
        return isinstance(tokens[start], ScalarValue)
    else:
        return False
function mapping_node_from_tokens(tokens: List['Token'], start: int) -> Tuple['MappingNode', int]
function sequence_node_from_tokens(tokens: List['Token'], start: int) -> Tuple['SequenceNode', int]
function scalar_node_from_tokens(tokens: List['Token'], start: int) -> Tuple['ScalarNode', int]
is_scalar(tokens=tokens, start=start)
return mapping_node_from_tokens(tokens=tokens, start=start)
return sequence_node_from_tokens(tokens=tokens, start=start)
return scalar_node_from_tokens(tokens=tokens, start=start)
return isinstance(tokens[start], MappingStart)
keyNode = scalar_node_from_tokens(tokens=tokens, start=currentPosition)[0]
lastPosition = scalar_node_from_tokens(tokens=tokens, start=currentPosition)[1]
valueNode = node_from_tokens(tokens=tokens, start=lastPosition + 1)[0]
lastPosition = node_from_tokens(tokens=tokens, start=lastPosition + 1)[1]
return isinstance(tokens[start], SequenceStart)
valueNode = node_from_tokens(tokens=tokens, start=currentPosition)[0]
lastPosition = node_from_tokens(tokens=tokens, start=currentPosition)[1]
return isinstance(tokens[start], ScalarValue)
return (ScalarNode(data=tokens[start].data), start + 1)
currentPosition = start + 1
is_scalar(tokens=[ScalarValue(data='value')], start=0)
[RECOMMENDATION_TYPES]
[TYPE] Token
[DEFINITION]
class Token:
    pass
[TYPE] Delimiter
[DEFINITION]
class Delimiter(Token):
    pass
[TYPE] MappingEnd
[DEFINITION]
class MappingEnd(Token):
    pass
[TYPE] MappingStart
[DEFINITION]
class MappingStart(Token):
    pass
[TYPE] ScalarValue
[DEFINITION]
class ScalarValue(Token):
    data: str
[TYPE] Separator
[DEFINITION]
class Separator(Token):
    pass
[TYPE] SequenceEnd
[DEFINITION]
class SequenceEnd(Token):
    pass
[TYPE] SequenceStart
[DEFINITION]
class SequenceStart(Token):
    pass
[TYPE] Enum
[DEFINITION]
class Enum(metaclass=EnumMeta):
    # package: enum
    # module: enum
    # source: typeshed
    # public methods
    def name(self) -> str:
    def value(self) -> Any:
[TYPE] MappingNode
[DEFINITION]
class MappingNode(Node):
    mapping: typing.Dict['ScalarNode', 'Node']
```

### Sai 2: nhãn `List[LowLevelSchedulingStats]`, model dự đoán `List[str]`

- ID: `be9/mypy-problem:repos/be9/mypy-problem/planner/scheduling/make_schedule.py:18871:make_schedule`
- Project: `be9/mypy-problem`
- Hàm đích: `make_schedule`
- Phạm vi: `return`
- Nhãn: `List[LowLevelSchedulingStats]`
- Dự đoán thô: `List[str]`
- Dự đoán chuẩn hóa: `List[str]`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] make_schedule
[TARGET_FUNCTION] make_schedule
[TARGET_SCOPE] return
[INTERPROCEDURAL_SLICE]
from dataclasses import dataclass
from typing import Sequence
def make_schedule() -> <mask>:
    return []
[RECOMMENDATION_TYPES]
[TYPE] Sequence
[DEFINITION]
class Sequence(Reversible[_T_co], Collection[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, index: int, /) -> _T_co:
    def __getitem__(self, index: slice[int | None], /) -> Sequence[_T_co]:
    def index(self, value: Any, start: int=0, stop: int=..., /) -> int:
    def count(self, value: Any, /) -> int:
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] LowLevelSchedulingStats
[DEFINITION]
class LowLevelSchedulingStats:
    """Low-level stats."""
    pass
[TYPE] MutableSequence
[DEFINITION]
class MutableSequence(Sequence[_T]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def insert(self, index: int, value: _T, /) -> None:
    def __getitem__(self, index: int, /) -> _T:
    def __getitem__(self, index: slice[int | None], /) -> MutableSequence[_T]:
    def append(self, value: _T, /) -> None:
    def clear(self) -> None:
    def extend(self, values: Iterable[_T], /) -> None:
    def reverse(self) -> None:
    def pop(self, index: int=-1, /) -> _T:
    def remove(self, value: _T, /) -> None:
[TYPE] _DataclassFactory
[DEFINITION]
@type_check_only
class _DataclassFactory(Protocol):
    # package: dataclasses
    # module: dataclasses
    # source: typeshed
    # public methods
    def __call__(self, cls: type[_T], /, *, init: bool=True, repr: bool=True, eq: bool=True, order: bool=False, unsafe_hash: bool=False, frozen: bool=False, match_args: bool=True, kw_only: bool=False, slots: bool=False, weakref_slot: bool=False) -> type[_T]:
[TYPE] _DefaultFactory
[DEFINITION]
@type_check_only
class _DefaultFactory(Protocol[_T_co]):
    # package: dataclasses
    # module: dataclasses
    # source: typeshed
    # public methods
    def __call__(self) -> _T_co:
[TYPE] InitVar
[DEFINITION]
class InitVar(Generic[_T]):
    # package: dataclasses
    # module: dataclasses
    # source: typeshed
    # fields
    type: Type[_T]
    # public methods
    def __init__(self, type: Type[_T]) -> None:
[TYPE] ScheduleBuilder
[DEFINITION]
class ScheduleBuilder(abc.ABC):
    """Base class for schedule builders."""

    @dataclass(frozen=True)
    class Results:
        pass

    @abc.abstractmethod
    def build(self) -> None:
        pass
[TYPE] RandyScheduleBuilder
[DEFINITION]
class RandyScheduleBuilder(ScheduleBuilder):
    @dataclass(frozen=True)
    class Results(ScheduleBuilder.Results):
        """Extends ScheduleBuilder.Results with algorithm-specific results."""
        details: str

    def build(self) -> None:
        pass
[TYPE] _Alias
[DEFINITION]
@type_check_only
class _Alias:
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, typeargs: Any) -> Any:
[TYPE] _SpecialForm
[DEFINITION]
@final
class _SpecialForm(_Final):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, parameters: Any) -> object:
```

### Sai 3: nhãn `int`, model dự đoán `str`

- ID: `kelsos/test-environment-scripts:repos/kelsos/test-environment-scripts/raiden_api/model/data.py:35177:channel_identifier`
- Project: `kelsos/test-environment-scripts`
- Hàm đích: `Channel.__init__`
- Phạm vi: `arg`
- Nhãn: `int`
- Dự đoán thô: `str`
- Dự đoán chuẩn hóa: `str`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] channel_identifier
[TARGET_FUNCTION] Channel.__init__
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
import typing
def __init__(self, token_network_identifier: str, channel_identifier: <mask>, partner_address: str, token_address: str, balance: int, total_deposit: int, state: str, settle_timeout: int, reveal_timeout: int):
    self.token_network_identifier = token_network_identifier
    self.channel_identifier = channel_identifier
    self.partner_address = partner_address
    self.token_address = token_address
    self.balance = balance
    self.total_deposit = total_deposit
    self.state = state
    self.settle_timeout = settle_timeout
    self.reveal_timeout = reveal_timeout
[RECOMMENDATION_TYPES]
[TYPE] _ContainerT_contra
[DEFINITION]
class _ContainerT_contra:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('_ContainerT_contra', contravariant=True, default=Any)
[TYPE] _SpecialForm
[DEFINITION]
@final
class _SpecialForm(_Final):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, parameters: Any) -> object:
[TYPE] Container
[DEFINITION]
@runtime_checkable
class Container(Protocol[_ContainerT_contra]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] AnyStr
[DEFINITION]
class AnyStr:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('AnyStr', str, bytes)
[TYPE] AsyncGenerator
[DEFINITION]
@runtime_checkable
class AsyncGenerator(AsyncIterator[_YieldT_co], Protocol[_YieldT_co, _SendT_contra]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def asend(self, value: _SendT_contra, /) -> Coroutine[Any, Any, _YieldT_co]:
    def athrow(self, typ: type[BaseException], val: BaseException | object=None, tb: TracebackType | None=None, /) -> Coroutine[Any, Any, _YieldT_co]:
    def athrow(self, typ: BaseException, val: None=None, tb: TracebackType | None=None, /) -> Coroutine[Any, Any, _YieldT_co]:
    def aclose(self) -> Coroutine[Any, Any, None]:
[TYPE] AsyncIterable
[DEFINITION]
@runtime_checkable
class AsyncIterable(Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] AsyncIterator
[DEFINITION]
@runtime_checkable
class AsyncIterator(AsyncIterable[_T_co], Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] Iterable
[DEFINITION]
@runtime_checkable
class Iterable(Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] Iterator
[DEFINITION]
@runtime_checkable
class Iterator(Iterable[_T_co], Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] Sequence
[DEFINITION]
class Sequence(Reversible[_T_co], Collection[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, index: int, /) -> _T_co:
    def __getitem__(self, index: slice[int | None], /) -> Sequence[_T_co]:
    def index(self, value: Any, start: int=0, stop: int=..., /) -> int:
    def count(self, value: Any, /) -> int:
    def __iter__(self) -> Iterator[_T_co]:
```

### Sai 4: nhãn `list`, model dự đoán `List[int]`

- ID: `jasperges/pose-thumbnails:repos/jasperges/pose-thumbnails/pose_thumbnails/flip.py:33631:values`
- Project: `jasperges/pose-thumbnails`
- Hàm đích: `pixels`
- Phạm vi: `arg`
- Nhãn: `list`
- Dự đoán thô: `List[int]`
- Dự đoán chuẩn hóa: `List[int]`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] values
[TARGET_FUNCTION] pixels
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
import typing
import bpy
import mathutils
import string
import doctest
def pixels(values: <mask>, width: int, height: int):
    """In-place flips the pixels of an image."""
    start = 0
    end = width
    for _ in range(height):
        values[start:end] = reversed(values[start:end])
        start = end
        end += width
flip.pixels(image.image_pixels, *image.image_size)
flip.pixels(img.image_pixels, *img.image_size)
[RECOMMENDATION_TYPES]
[TYPE] MutableSequence
[DEFINITION]
class MutableSequence(Sequence[_T]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def insert(self, index: int, value: _T, /) -> None:
    def __getitem__(self, index: int, /) -> _T:
    def __getitem__(self, index: slice[int | None], /) -> MutableSequence[_T]:
    def append(self, value: _T, /) -> None:
    def clear(self) -> None:
    def extend(self, values: Iterable[_T], /) -> None:
    def reverse(self) -> None:
    def pop(self, index: int=-1, /) -> _T:
    def remove(self, value: _T, /) -> None:
[TYPE] DocTest
[DEFINITION]
class DocTest:
    # package: doctest
    # module: doctest
    # source: typeshed
    # fields
    examples: list[Example]
    globs: dict[str, Any]
    name: str
    filename: str | None
    lineno: int | None
    docstring: str | None
    # public methods
    def __init__(self, examples: list[Example], globs: dict[str, Any], name: str, filename: str | None, lineno: int | None, docstring: str | None) -> None:
[TYPE] ValuesView
[DEFINITION]
class ValuesView(MappingView, Collection[_VT_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __init__(self, mapping: SupportsGetItemViewable[Any, _VT_co]) -> None:
    def __iter__(self) -> Iterator[_VT_co]:
[TYPE] _Alias
[DEFINITION]
@type_check_only
class _Alias:
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, typeargs: Any) -> Any:
[TYPE] MutableSet
[DEFINITION]
class MutableSet(AbstractSet[_T]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def add(self, value: _T, /) -> None:
    def discard(self, value: _T, /) -> None:
    def clear(self) -> None:
    def pop(self) -> _T:
    def remove(self, value: _T, /) -> None:
[TYPE] Mapping
[DEFINITION]
class Mapping(Collection[_KT], Generic[_KT, _VT_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, key: _KT, /) -> _VT_co:
    def get(self, key: _KT, /) -> _VT_co | None:
    def get(self, key: _KT, default: _VT_co, /) -> _VT_co:
    def get(self, key: _KT, default: _T, /) -> _VT_co | _T:
    def items(self) -> ItemsView[_KT, _VT_co]:
    def keys(self) -> KeysView[_KT]:
    def values(self) -> ValuesView[_VT_co]:
[TYPE] Hashable
[DEFINITION]
@runtime_checkable
class Hashable(Protocol, metaclass=ABCMeta):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] Iterable
[DEFINITION]
@runtime_checkable
class Iterable(Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] Awaitable
[DEFINITION]
@runtime_checkable
class Awaitable(Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] NamedTuple
[DEFINITION]
class NamedTuple(tuple[Any, ...]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __init__(self, typename: str, fields: Iterable[tuple[str, Any]], /) -> None:
    def __init__(self, typename: str, fields: None=None, /, **kwargs: Any) -> None:
```

### Sai 5: nhãn `List[str]`, model dự đoán `List[List[int]]`

- ID: `JamesHageman/leetcode:repos/JamesHageman/leetcode/336.py:5667:words`
- Project: `JamesHageman/leetcode`
- Hàm đích: `Solution.palindromePairs`
- Phạm vi: `arg`
- Nhãn: `List[str]`
- Dự đoán thô: `List[List[int]]`
- Dự đoán chuẩn hóa: `List[List[int]]`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] words
[TARGET_FUNCTION] Solution.palindromePairs
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from typing import List
import sys
def palindromePairs(self, words: <mask>) -> List[List[int]]:
    A = []
    for i in range(len(words)):
        for j in range(len(words)):
            if j == i:
                continue
            if is_palindrome(words[i], words[j]):
                A.append([i, j])
    return A
s.palindromePairs(sys.argv[1:])
[RECOMMENDATION_TYPES]
[TYPE] _ExitCode
[DEFINITION]
class _ExitCode:
    # package: sys
    # module: sys
    # source: typeshed
    # kind: alias
    # type alias: str | int | None
[TYPE] _LazyImportMode
[DEFINITION]
class _LazyImportMode:
    # package: sys
    # module: sys
    # source: typeshed
    # kind: alias
    # type alias: Literal['normal', 'all', 'none']
[TYPE] _asyncgen_hooks
[DEFINITION]
@final
@type_check_only
class _asyncgen_hooks(structseq[_AsyncgenHook], tuple[_AsyncgenHook, _AsyncgenHook]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def firstiter(self) -> _AsyncgenHook:
    def finalizer(self) -> _AsyncgenHook:
[TYPE] _flags
[DEFINITION]
@final
@type_check_only
class _flags(_UninstantiableStructseq, tuple[int, ...]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def debug(self) -> int:
    def inspect(self) -> int:
    def interactive(self) -> int:
    def optimize(self) -> int:
    def dont_write_bytecode(self) -> int:
    def no_user_site(self) -> int:
    def no_site(self) -> int:
    def ignore_environment(self) -> int:
    def verbose(self) -> int:
    def bytes_warning(self) -> int:
    def quiet(self) -> int:
    def hash_randomization(self) -> int:
    def isolated(self) -> int:
    def dev_mode(self) -> bool:
    def utf8_mode(self) -> int:
    def warn_default_encoding(self) -> int:
    def int_max_str_digits(self) -> int:
[TYPE] UnraisableHookArgs
[DEFINITION]
@type_check_only
class UnraisableHookArgs(Protocol):
    # package: sys
    # module: sys
    # source: typeshed
    # fields
    exc_type: type[BaseException]
    exc_value: BaseException | None
    exc_traceback: TracebackType | None
    err_msg: str | None
    object: _object
[TYPE] _ReleaseLevel
[DEFINITION]
class _ReleaseLevel:
    # package: sys
    # module: sys
    # source: typeshed
    # kind: alias
    # type alias: Literal['alpha', 'beta', 'candidate', 'final']
[TYPE] _int_info
[DEFINITION]
@final
@type_check_only
class _int_info(structseq[int], tuple[int, int, int, int]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def bits_per_digit(self) -> int:
    def sizeof_digit(self) -> int:
    def default_max_str_digits(self) -> int:
    def str_digits_check_threshold(self) -> int:
[TYPE] _hash_info
[DEFINITION]
@final
@type_check_only
class _hash_info(structseq[Any | int], tuple[int, int, int, int, int, str, int, int, int]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def width(self) -> int:
    def modulus(self) -> int:
    def inf(self) -> int:
    def nan(self) -> int:
    def imag(self) -> int:
    def algorithm(self) -> str:
    def hash_bits(self) -> int:
    def seed_bits(self) -> int:
    def cutoff(self) -> int:
[TYPE] _LazyImportFilter
[DEFINITION]
class _LazyImportFilter:
    # package: sys
    # module: sys
    # source: typeshed
    # kind: alias
    # type alias: Callable[[str | None, str, tuple[str, ...] | None], bool]
[TYPE] _float_info
[DEFINITION]
@final
@type_check_only
class _float_info(structseq[float], tuple[float, int, int, float, int, int, int, int, float, int, int]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def max(self) -> float:
    def max_exp(self) -> int:
    def max_10_exp(self) -> int:
    def min(self) -> float:
    def min_exp(self) -> int:
    def min_10_exp(self) -> int:
    def dig(self) -> int:
    def mant_dig(self) -> int:
    def epsilon(self) -> float:
    def radix(self) -> int:
    def rounds(self) -> int:
```


## 5 ví dụ đúng với kiểu user-defined/named

### Kiểu user-defined — đúng 1: `repository` → `Repository`

- ID: `flexiooss/flexio-flow:repos/flexiooss/flexio-flow/src/PoomCiDependency/FullRepository.py:28352:repository`
- Project: `flexiooss/flexio-flow`
- Hàm đích: `FullRepository.from_repository`
- Phạm vi: `arg`
- Nhãn: `Repository`
- Dự đoán thô: `Repository`
- Dự đoán chuẩn hóa: `Repository`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] repository
[TARGET_FUNCTION] FullRepository.from_repository
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from __future__ import annotations
from typing import List
from PoomCiDependency.Module import Module
from PoomCiDependency.Repository import Repository
class FullRepository:
    # fields
    id: str
    name: str
    checkoutSpec: str
    dependencies: List[Module] = []
    produces: List[Module] = []
    # methods
    def __init__(self, id, name, checkout_spec):
    def from_repository(repository) -> FullRepository:
    def append_dependency(self, dependency) -> FullRepository:
    def append_produce(self, produce) -> FullRepository:
@staticmethod
def from_repository(repository: <mask>) -> FullRepository:
    return FullRepository(repository.id, repository.name, repository.checkout_spec)
FullRepository.from_repository(self.repository)
[RECOMMENDATION_TYPES]
[TYPE] FullRepository
[DEFINITION]
class FullRepository:
    id: str
    name: str
    checkoutSpec: str
    dependencies: List[Module] = []
    produces: List[Module] = []

    def __init__(self, id: str, name: str, checkout_spec: str):
        self.id = id
        self.name = name
        self.checkout_spec = checkout_spec
        self.dependencies = []
        self.produces = []

    @staticmethod
    def from_repository(repository: ((<mask>))) -> FullRepository:
        return FullRepository(repository.id, repository.name, repository.checkout_spec)

    def append_dependency(self, dependency: Module) -> FullRepository:
        self.dependencies.append(dependency)
        return self

    def append_produce(self, produce: Module) -> FullRepository:
        self.produces.append(produce)
        return self
[TYPE] Repository
[DEFINITION]
class Repository:
    id: str
    name: str
    checkout_spec: str

    def __init__(self, id: str, name: str, checkout_spec: str):
        self.id = id
        self.name = name
        self.checkout_spec = checkout_spec
[TYPE] Module
[DEFINITION]
class Module:
    spec: str
    version: str

    def __init__(self, spec: str, version: str):
        self.spec = spec
        self.version = version
[TYPE] List
[DEFINITION]
class List(list, Static):
    # package: setuptools
    # module: setuptools._static
    # source: third_party
    pass
[TYPE] PoomCiDependency
[DEFINITION]
class PoomCiDependency:

    def __init__(self, action: Actions, state_handler: StateHandler, options: Options):
        self.action: Actions = action
        self.state_handler: StateHandler = state_handler
        self.options: Options = options

    def process(self):
        if self.action is Actions.FULL_REPOSITORY_JSON:

            FullRepositoryJsonAction(self.state_handler, self.options).process()
        else:
            raise ValueError("Bad PoomCiDependency Action : " + self.action.name)
[TYPE] FullRepositoryBuilder
[DEFINITION]
class FullRepositoryBuilder:
    repository: Optional[Repository] = None

    def __init__(self, state_handler: StateHandler, options: Options):
        self.state_handler: StateHandler = state_handler
        self.options: Options = options

    def __ensure_have_repo(self):

        repository_id: str = self.options.repository_id
        repository_name = self.options.repository_name
        repository_checkout_spec = self.options.repository_checkout_spec

        if repository_id is None or repository_name is None or repository_checkout_spec is None:
            raise ValueError('Option missing, repository_id, repository_name, repository_checkout_spec')

        self.repository = Repository(id=repository_id, name=repository_name, checkout_spec=repository_checkout_spec)

    def __get_scheme_option_or_default(self) -> Schemes:
        schemes: Optional[Schemes] = self.options.scheme
        if schemes is None:
            schemes = self.state_handler.first_scheme()
        if schemes is None:
            raise ValueError('No schemes given')
        return schemes

    def build(self) -> FullRepository:
        self.__ensure_have_repo()

        full_repository: FullRepository = FullRepository.from_repository(self.repository)

        scheme: Scheme = SchemeBuilder.create(self.__get_scheme_option_or_default(), self.state_handler)

        poom_ci_dependencies: Optional[List[Module]] = scheme.get_poom_ci_dependencies()
        if poom_ci_dependencies is not None:
            full_repository.dependencies = poom_ci_dependencies

        poom_ci_produces: Optional[List[Module]] = scheme.get_poom_ci_produces()
        if poom_ci_produces is not None:
            full_repository.produces = poom_ci_produces

        return full_repository
[TYPE] RepositoryId
[DEFINITION]
class RepositoryId(Option):
    HAS_VALUE = True
    SHORT_NAME = None
    NAME = 'repository-id'

    def exec(self) -> Options:
        self.options.repository_id = self.clean_space(str(self.arg))
        return self.options
[TYPE] RepositoryName
[DEFINITION]
class RepositoryName(Option):
    HAS_VALUE = True
    SHORT_NAME = None
    NAME = 'repository-name'

    def exec(self) -> Options:
        self.options.repository_name = self.clean_space(str(self.arg))
        return self.options
[TYPE] RepositoryCheckoutSpec
[DEFINITION]
class RepositoryCheckoutSpec(Option):
    HAS_VALUE = True
    SHORT_NAME = None
    NAME = 'repository-checkout-spec'

    def exec(self) -> Options:
        self.options.repository_checkout_spec = self.clean_space(str(self.arg))
        return self.options
[TYPE] FullRepositoryJsonAction
[DEFINITION]
class FullRepositoryJsonAction:
    repository: Optional[Repository] = None

    def __init__(self, state_handler: StateHandler, options: Options):
        self.state_handler: StateHandler = state_handler
        self.options: Options = options

    def process(self):
        full_repository: FullRepository = FullRepositoryBuilder(self.state_handler, self.options).build()

        if self.options.filename is not None:
            filename: Path = Path(self.options.filename)

            if filename.is_file():
                raise FileExistsError(filename)

            with filename.open('w+') as outfile:
                outfile.write(PoomCiDependencyJSONEncoder().encode(full_repository))

        else:
            print(PoomCiDependencyJSONEncoder().encode(full_repository))
```

### Kiểu user-defined — đúng 2: `summary` → `BenchmarkResults`

- ID: `povilasb/httpmeter:repos/povilasb/httpmeter/httpmeter/stats.py:45277:summary`
- Project: `povilasb/httpmeter`
- Hàm đích: `ForBenchmark.summary`
- Phạm vi: `return`
- Nhãn: `BenchmarkResults`
- Dự đoán thô: `BenchmarkResults`
- Dự đoán chuẩn hóa: `BenchmarkResults`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] summary
[TARGET_FUNCTION] ForBenchmark.summary
[TARGET_SCOPE] return
[INTERPROCEDURAL_SLICE]
import sys
import time
from typing import Dict, List, Any, Iterable, Tuple
from functools import reduce
from itertools import tee
from . import utils
class BenchmarkResults:
    # methods
    def __init__(self, min_doc_len, avg_doc_len, max_doc_len, concurrency, completed_requests, reqs_per_sec, min_req_time, avg_req_time, max_req_time, status_codes) -> None:
function completed_requests(self) -> int
function status_codes(self) -> Dict[int, int]
function min_avg_max(iter_: Iterable[float]) -> Tuple[int, float, int]
function content_sizes(self) -> Iterable[int]
function durations(self) -> Iterable[float]
def summary(self) -> <mask>:
    return BenchmarkResults(*min_avg_max(self.content_sizes()), self.concurrency, self.completed_requests(), self.completed_requests() / self.duration, *min_avg_max(self.durations()), self.status_codes())
stats.ForBenchmark(requests_stats, conf.concurrency * conf.process_count, duration).summary()
bench_stats.summary()
[RECOMMENDATION_TYPES]
[TYPE] ForBenchmark
[DEFINITION]
class ForBenchmark:
    """Stats for whole benchmark."""

    def __init__(self, stats: List[ForRequest], concurrency: int=1,
                 total_duration: float=1) -> None:
        self.stats = stats
        self.concurrency = concurrency
        self.duration = total_duration

    def content_sizes(self) -> Iterable[int]:
        return map(lambda entry: entry.content_size, self.stats)

    def durations(self) -> Iterable[float]:
        return map(lambda entry: entry.duration, self.stats)

    def status_codes(self) -> Dict[int, int]:
        return reduce(lambda codes, entry: inc(codes, entry.status_code),
                      self.stats, {})

    def completed_requests(self) -> int:
        return len(self.stats)

    def summary(self) -> ((<mask>)):
        return BenchmarkResults(
            *min_avg_max(self.content_sizes()),
            self.concurrency, self.completed_requests(),
            self.completed_requests() / self.duration,
            *min_avg_max(self.durations()),
            self.status_codes()
        )
[TYPE] BenchmarkResults
[DEFINITION]
class BenchmarkResults:
    def __init__(self, min_doc_len: int, avg_doc_len: float, max_doc_len: int,
                 concurrency: int, completed_requests: int,
                 reqs_per_sec: float, min_req_time: int, avg_req_time: float,
                 max_req_time: int, status_codes: Dict[int, int]) -> None:
        self.min_doc_len = min_doc_len
        self.avg_doc_len = avg_doc_len
        self.max_doc_len = max_doc_len
        self.concurrency = concurrency
        self.completed_requests = completed_requests
        self.reqs_per_sec = reqs_per_sec
        self.min_req_time = min_req_time
        self.avg_req_time = avg_req_time
        self.max_req_time = max_req_time
        self.status_codes = status_codes
[TYPE] Iterable
[DEFINITION]
@runtime_checkable
class Iterable(Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] Any
[DEFINITION]
class Any:
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] ANY
[DEFINITION]
class ANY:
    # package: asynctest
    # module: asynctest.mock
    # source: third_party
    # kind: alias
    # type alias: unittest.mock.ANY
[TYPE] Dict
[DEFINITION]
class Dict(dict, Static):
    # package: setuptools
    # module: setuptools._static
    # source: third_party
    pass
[TYPE] List
[DEFINITION]
class List(list, Static):
    # package: setuptools
    # module: setuptools._static
    # source: third_party
    pass
[TYPE] Tuple
[DEFINITION]
class Tuple(tuple, Static):
    # package: setuptools
    # module: setuptools._static
    # source: third_party
    pass
[TYPE] Metadata
[DEFINITION]
class Metadata:
    # package: setuptools
    # module: setuptools._vendor.packaging.metadata
    # source: third_party
    # fields
    metadata_version: _Validator[_MetadataVersion] = _Validator()
    name: _Validator[str] = _Validator()
    version: _Validator[version_module.Version] = _Validator()
    dynamic: _Validator[list[str] | None] = _Validator(added='2.2')
    platforms: _Validator[list[str] | None] = _Validator()
    supported_platforms: _Validator[list[str] | None] = _Validator(added='1.1')
    summary: _Validator[str | None] = _Validator()
    description: _Validator[str | None] = _Validator()
    description_content_type: _Validator[str | None] = _Validator(added='2.1')
    keywords: _Validator[list[str] | None] = _Validator()
    home_page: _Validator[str | None] = _Validator()
    download_url: _Validator[str | None] = _Validator(added='1.1')
    author: _Validator[str | None] = _Validator()
    author_email: _Validator[str | None] = _Validator()
    maintainer: _Validator[str | None] = _Validator(added='1.2')
    maintainer_email: _Validator[str | None] = _Validator(added='1.2')
    license: _Validator[str | None] = _Validator()
    license_expression: _Validator[NormalizedLicenseExpression | None] = _Validator(added='2.4')
    license_files: _Validator[list[str] | None] = _Validator(added='2.4')
    classifiers: _Validator[list[str] | None] = _Validator(added='1.1')
    requires_dist: _Validator[list[requirements.Requirement] | None] = _Validator(added='1.2')
    requires_python: _Validator[specifiers.SpecifierSet | None] = _Validator(added='1.2')
    requires_external: _Validator[list[str] | None] = _Validator(added='1.2')
    project_urls: _Validator[dict[str, str] | None] = _Validator(added='1.2')
    provides_extra: _Validator[list[utils.NormalizedName] | None] = _Validator(added='2.1')
    provides_dist: _Validator[list[str] | None] = _Validator(added='1.2')
    obsoletes_dist: _Validator[list[str] | None] = _Validator(added='1.2')
    import_names: _Validator[list[str] | None] = _Validator(added='2.5')
    import_namespaces: _Validator[list[str] | None] = _Validator(added='2.5')
    requires: _Validator[list[str] | None] = _Validator(added='1.1')
    provides: _Validator[list[str] | None] = _Validator(added='1.1')
    obsoletes: _Validator[list[str] | None] = _Validator(added='1.1')
    # public methods
    def from_raw(cls, data: RawMetadata, *, validate: bool=True) -> Metadata:
    def from_email(cls, data: bytes | str, *, validate: bool=True) -> Metadata:
    def as_rfc822(self) -> RFC822Message:
[TYPE] ConfigMetadataHandler
[DEFINITION]
class ConfigMetadataHandler(ConfigHandler['DistributionMetadata']):
    # package: setuptools
    # module: setuptools.config.setupcfg
    # source: third_party
    # fields
    section_prefix = 'metadata'
    aliases: ClassVar[dict[str, str]] = {'home_page': 'url', 'summary': 'description', 'classifier': 'classifiers', 'platform': 'platforms'}
    strict_mode = False
    # public methods
    def __init__(self, target_obj: DistributionMetadata, options: AllCommandOptions, ignore_option_errors: bool, ensure_discovered: expand.EnsurePackagesDiscovered, package_dir: dict | None=None, root_dir: StrPath | None=os.curdir) -> None:
    def parsers(self) -> dict[str, Callable]:
```

### Kiểu user-defined — đúng 3: `request` → `Request`

- ID: `aio-libs/aiozipkin:repos/aio-libs/aiozipkin/tests/conftest.py:12746:request`
- Project: `aio-libs/aiozipkin`
- Hàm đích: `FakeZipkin.spans_handler`
- Phạm vi: `arg`
- Nhãn: `Request`
- Dự đoán thô: `Request`
- Dự đoán chuẩn hóa: `Request`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] request
[TARGET_FUNCTION] FakeZipkin.spans_handler
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
import asyncio
import gc
from typing import Any, AsyncIterator, Iterator, List, Optional
import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiozipkin.helpers import TraceContext, create_endpoint
from aiozipkin.sampler import Sampler
from aiozipkin.tracer import Tracer
from aiozipkin.transport import StubTransport
function close(self) -> None
async def spans_handler(self, request: <mask>) -> web.Response:
    if len(self.next_errors) > 0:
        err = self.next_errors.pop(0)
        if err == 'disconnect':
            assert request.transport is not None
            request.transport.close()
            await asyncio.sleep(1)
        elif err == 'timeout':
            await asyncio.sleep(60)
        return web.HTTPInternalServerError()
    data = await request.json()
    if self._wait_count is not None:
        self._wait_count -= 1
    self._received_data.append(data)
    if self._wait_fut is not None and self._wait_count == 0:
        self._wait_fut.set_result(None)
    return aiohttp.web.Response(text='', status=200)
[RECOMMENDATION_TYPES]
[TYPE] Tracer
[DEFINITION]
class Tracer(_Base):
    def __init__(
        self,
        transport: TransportABC,
        sampler: SamplerABC,
        local_endpoint: Endpoint,
        ignored_exceptions: Optional[List[Type[Exception]]] = None,
    ) -> None:
        super().__init__()
        self._records: Dict[TraceContext, Record] = {}
        self._transport = transport
        self._sampler = sampler
        self._local_endpoint = local_endpoint
        self._ignored_exceptions = ignored_exceptions or []

    def new_trace(self, sampled: OptBool = None, debug: bool = False) -> SpanAbc:
        context = self._next_context(None, sampled=sampled, debug=debug)
        return self.to_span(context)

    def join_span(self, context: TraceContext) -> SpanAbc:
        new_context = context
        if context.sampled is None:
            sampled = self._sampler.is_sampled(context.trace_id)
            new_context = new_context._replace(sampled=sampled)
        else:
            new_context = new_context._replace(shared=True)
        return self.to_span(new_context)

    def new_child(self, context: TraceContext) -> SpanAbc:
        new_context = self._next_context(context)
        if not context.sampled:
            return NoopSpan(self, new_context, self._ignored_exceptions)
        return self.to_span(new_context)

    def to_span(self, context: TraceContext) -> SpanAbc:
        if not context.sampled:
            return NoopSpan(self, context, self._ignored_exceptions)

        record = Record(context, self._local_endpoint)
        self._records[context] = record
        return Span(self, context, record, self._ignored_exceptions)

    def _send(self, record: Record) -> None:
        self._records.pop(record.context, None)
        self._transport.send(record)

    def _next_context(
        self,
        context: Optional[TraceContext] = None,
        sampled: OptBool = None,
        debug: bool = False,
    ) -> TraceContext:
        span_id = generate_random_64bit_string()
        if context is not None:
            new_context = context._replace(
                span_id=span_id, parent_id=context.span_id, shared=False
            )
            return new_context

        trace_id = generate_random_128bit_string()
        if sampled is None:
            sampled = self._sampler.is_sampled(trace_id)

        new_context = TraceContext(
            trace_id=trace_id,
            parent_id=None,
            span_id=span_id,
            sampled=sampled,
            debug=debug,
            shared=False,
        )
        return new_context

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> "Tracer":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
[TYPE] List
[DEFINITION]
class List(Literal):
    # package: jinja2
    # module: jinja2.nodes
    # source: third_party
    # fields
    fields = ('items',)
    items: t.List[Expr]
    # public methods
    def as_const(self, eval_ctx: t.Optional[EvalContext]=None) -> t.List[t.Any]:
[TYPE] TestServer
[DEFINITION]
class TestServer(BaseTestServer):
    # package: aiohttp
    # module: aiohttp.test_utils
    # source: third_party
    # public methods
    def __init__(self, app: Application, *, scheme: str='', host: str='127.0.0.1', port: Optional[int]=None, **kwargs: Any):
[TYPE] Any
[DEFINITION]
class Any:
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] Iterator
[DEFINITION]
@runtime_checkable
class Iterator(Iterable[_T_co], Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] Request
[DEFINITION]
class Request(BaseRequest):
    # package: aiohttp
    # module: aiohttp.web_request
    # source: third_party
    # fields
    ATTRS = BaseRequest.ATTRS | frozenset(['_match_info'])
    # public methods
    def clone(self, *, method: Union[str, _SENTINEL]=sentinel, rel_url: Union[StrOrURL, _SENTINEL]=sentinel, headers: Union[LooseHeaders, _SENTINEL]=sentinel, scheme: Union[str, _SENTINEL]=sentinel, host: Union[str, _SENTINEL]=sentinel, remote: Union[str, _SENTINEL]=sentinel, client_max_size: Union[int, _SENTINEL]=sentinel) -> 'Request':
    def match_info(self) -> 'UrlMappingMatchInfo':
    def app(self) -> 'Application':
    def config_dict(self) -> ChainMapProxy:
[TYPE] TraceContext
[DEFINITION]
class TraceContext(_TraceContext):
    """Immutable class with trace related data that travels across
    process boundaries.
    """

    def make_headers(self) -> Headers:
        """Creates dict with zipkin headers from available context.

        Resulting dict should be passed to HTTP client  propagate contest
        to other services.
        """
        return make_headers(self)

    def make_single_header(self) -> Headers:
        return make_single_header(self)
[TYPE] AsyncIterator
[DEFINITION]
@runtime_checkable
class AsyncIterator(AsyncIterable[_T_co], Protocol[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] StubTransport
[DEFINITION]
class StubTransport(TransportABC):
    """Dummy transport, which logs spans to a limited queue."""

    def __init__(self, queue_length: int = 100) -> None:
        logger.info("Zipkin address was not provided, using stub transport")
        self.records: Deque[Record] = deque(maxlen=queue_length)

    def send(self, record: Record) -> None:
        self.records.append(record)

    async def close(self) -> None:
        pass
[TYPE] Sampler
[DEFINITION]
class Sampler(SamplerABC):
    def __init__(self, *, sample_rate: float = 1.0, seed: OptInt = None) -> None:
        self._sample_rate = sample_rate
        self._rng = Random(seed)

    def is_sampled(self, trace_id: str) -> bool:
        if self._sample_rate == 0.0:
            sampled = False
        else:
            sampled = self._rng.random() <= self._sample_rate
        return sampled
```

### Kiểu user-defined — đúng 4: `config` → `Configurator`

- ID: `Pylons/pyramid_openapi3:repos/Pylons/pyramid_openapi3/pyramid_openapi3/__init__.py:8904:config`
- Project: `Pylons/pyramid_openapi3`
- Hàm đích: `add_formatter`
- Phạm vi: `arg`
- Nhãn: `Configurator`
- Dự đoán thô: `Configurator`
- Dự đoán chuẩn hóa: `Configurator`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] config
[TARGET_FUNCTION] add_formatter
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from .exceptions import MissingEndpointsError
from .exceptions import RequestValidationError
from .exceptions import ResponseValidationError
from .exceptions import extract_errors
from .wrappers import PyramidOpenAPIRequest
from jsonschema_path import SchemaPath
from openapi_core import V30ResponseValidator
from openapi_core import V31ResponseValidator
from openapi_core import V32ResponseValidator
from openapi_core.unmarshalling.request import V30RequestUnmarshaller
from openapi_core.unmarshalling.request import V31RequestUnmarshaller
from openapi_core.unmarshalling.request import V32RequestUnmarshaller
from openapi_core.validation.request.exceptions import SecurityValidationError
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename
from openapi_spec_validator.versions.shortcuts import get_spec_version
from pathlib import Path
from pathlib import PurePosixPath
from pyramid.config import PHASE0_CONFIG
from pyramid.config import PHASE1_CONFIG
from pyramid.config import Configurator
from pyramid.config.views import ViewDeriverInfo
from pyramid.events import ApplicationCreated
from pyramid.exceptions import ConfigurationError
from pyramid.httpexceptions import exception_response
from pyramid.path import AssetResolver
from pyramid.request import Request
from pyramid.response import FileResponse
from pyramid.response import Response
from pyramid.security import NO_PERMISSION_REQUIRED
from pyramid.settings import asbool
from pyramid.tweens import EXCVIEW
from string import Template
from urllib.parse import urlparse
import hupper
import json
import logging
import typing as t
def add_formatter(config: <mask>, name: str, func: t.Callable) -> None:
    """Add support for configuring formatters."""
    config.registry.settings.setdefault('pyramid_openapi3_formatters', {})
    reg = config.registry.settings['pyramid_openapi3_formatters']
    reg[name] = func
[RECOMMENDATION_TYPES]
[TYPE] Configurator
[DEFINITION]
class Configurator(ActionConfiguratorMixin, PredicateConfiguratorMixin, TestingConfiguratorMixin, TweensConfiguratorMixin, SecurityConfiguratorMixin, ViewsConfiguratorMixin, RoutesConfiguratorMixin, ZCAConfiguratorMixin, I18NConfiguratorMixin, RenderingConfiguratorMixin, AssetsConfiguratorMixin, SettingsConfiguratorMixin, FactoriesConfiguratorMixin, AdaptersConfiguratorMixin):
    # package: pyramid
    # module: pyramid.config
    # source: third_party
    # fields
    manager = manager
    venusian = venusian
    basepath = None
    includepath = ()
    info = ''
    object_description = staticmethod(object_description)
    introspectable = Introspectable
    inspect = inspect
    introspector = property(_get_introspector, _set_introspector, _del_introspector)
    absolute_resource_spec = absolute_asset_spec
    # public methods
    def __init__(self, registry=None, package=None, settings=None, root_factory=None, security_policy=None, authentication_policy=None, authorization_policy=None, renderers=None, debug_logger=None, locale_negotiator=None, request_factory=None, response_factory=None, default_permission=None, session_factory=None, default_view_mapper=None, autocommit=False, exceptionresponse_view=default_exceptionresponse_view, route_prefix=None, introspection=True, root_package=None):
    def setup_registry(self, settings=None, root_factory=None, security_policy=None, authentication_policy=None, authorization_policy=None, renderers=None, debug_logger=None, locale_negotiator=None, request_factory=None, response_factory=None, default_permission=None, session_factory=None, default_view_mapper=None, exceptionresponse_view=default_exceptionresponse_view):
    def include(self, callable, route_prefix=None):
    def add_directive(self, name, directive, action_wrap=True):
    def with_package(self, package):
    def maybe_dotted(self, dotted):
    def absolute_asset_spec(self, relative_spec):
    def begin(self, request=_marker):
    def end(self):
    def __enter__(self):
    def __exit__(self, exc_type, exc_value, exc_traceback):
    def scan(self, package=None, categories=('pyramid',), onerror=None, ignore=None, **kw):
    def make_wsgi_app(self):
[TYPE] ViewDeriverInfo
[DEFINITION]
@implementer(IViewDeriverInfo)
class ViewDeriverInfo:
    # package: pyramid
    # module: pyramid.config.views
    # source: third_party
    # public methods
    def __init__(self, view, registry, package, predicates, exception_only, options):
    def settings(self):
[TYPE] SchemaPath
[DEFINITION]
class SchemaPath(AccessorPath[SchemaNode, SchemaKey, SchemaValue]):
    # package: jsonschema_path
    # module: jsonschema_path.paths
    # source: third_party
    # public methods
    def from_dict(cls: type[TSchemaPath], data: Schema, *args: Any, separator: str=SPEC_SEPARATOR, specification: Specification[Schema]=DRAFT202012, base_uri: str='', handlers: ResolverHandlers=default_handlers, resolved_cache_maxsize: int=0, spec_url: str | None=None, ref_resolver_handlers: ResolverHandlers | None=None) -> TSchemaPath:
    def from_path(cls: type[TSchemaPath], path: Path, resolved_cache_maxsize: int=0) -> TSchemaPath:
    def from_file_path(cls: type[TSchemaPath], file_path: str, resolved_cache_maxsize: int=0) -> TSchemaPath:
    def from_file(cls: type[TSchemaPath], fileobj: SupportsRead, base_uri: str='', spec_url: str | None=None, resolved_cache_maxsize: int=0) -> TSchemaPath:
    def base_uri(self) -> str:
    def str_keys(self) -> Sequence[str]:
    def str_items(self) -> Iterator[tuple[str, SchemaPath]]:
    def read_str(self) -> str:
    def read_str(self, default: TDefault) -> str | TDefault:
    def read_str(self, default: object=NOTSET) -> object:
    def read_str_or_list(self) -> str | list[str]:
    def read_str_or_list(self, default: TDefault) -> str | list[str] | TDefault:
    def read_str_or_list(self, default: object=NOTSET) -> object:
    def read_bool(self) -> bool:
    def read_bool(self, default: TDefault) -> bool | TDefault:
    def read_bool(self, default: object=NOTSET) -> object:
    def as_uri(self) -> str:
    def open(self) -> Any:
    def resolve(self) -> Iterator[Resolved[SchemaNode]]:
[TYPE] V30ResponseValidator
[DEFINITION]
class V30ResponseValidator(APICallResponseValidator):
    # package: openapi_core
    # module: openapi_core.validation.response.validators
    # source: third_party
    # fields
    spec_validator_cls = OpenAPIV30SpecValidator
    schema_casters_factory = oas30_read_schema_casters_factory
    schema_validators_factory = oas30_read_schema_validators_factory
[TYPE] V31ResponseValidator
[DEFINITION]
class V31ResponseValidator(APICallResponseValidator):
    # package: openapi_core
    # module: openapi_core.validation.response.validators
    # source: third_party
    # fields
    spec_validator_cls = OpenAPIV31SpecValidator
    schema_casters_factory = oas31_schema_casters_factory
    schema_validators_factory = oas31_schema_validators_factory
[TYPE] V32ResponseValidator
[DEFINITION]
class V32ResponseValidator(APICallResponseValidator):
    # package: openapi_core
    # module: openapi_core.validation.response.validators
    # source: third_party
    # fields
    spec_validator_cls = OpenAPIV32SpecValidator
    schema_casters_factory = oas32_schema_casters_factory
    schema_validators_factory = oas32_schema_validators_factory
[TYPE] V30RequestUnmarshaller
[DEFINITION]
class V30RequestUnmarshaller(V30RequestValidator, APICallRequestUnmarshaller):
    # package: openapi_core
    # module: openapi_core.unmarshalling.request.unmarshallers
    # source: third_party
    # fields
    schema_unmarshallers_factory = oas30_write_schema_unmarshallers_factory
[TYPE] V31RequestUnmarshaller
[DEFINITION]
class V31RequestUnmarshaller(V31RequestValidator, APICallRequestUnmarshaller):
    # package: openapi_core
    # module: openapi_core.unmarshalling.request.unmarshallers
    # source: third_party
    # fields
    schema_unmarshallers_factory = oas31_schema_unmarshallers_factory
[TYPE] SecurityValidationError
[DEFINITION]
class SecurityValidationError(RequestValidationError):
    # package: openapi_core
    # module: openapi_core.validation.request.exceptions
    # source: third_party
    pass
[TYPE] V32RequestUnmarshaller
[DEFINITION]
class V32RequestUnmarshaller(V32RequestValidator, APICallRequestUnmarshaller):
    # package: openapi_core
    # module: openapi_core.unmarshalling.request.unmarshallers
    # source: third_party
    # fields
    schema_unmarshallers_factory = oas32_schema_unmarshallers_factory
```

### Kiểu user-defined — đúng 5: `client_session` → `ClientSession`

- ID: `danielhfrank/dawg:repos/danielhfrank/dawg/dawg/pushover.py:23552:client_session`
- Project: `danielhfrank/dawg`
- Hàm đích: `mk_pushover_notifier`
- Phạm vi: `arg`
- Nhãn: `ClientSession`
- Dự đoán thô: `ClientSession`
- Dự đoán chuẩn hóa: `ClientSession`
- Kết quả: **đúng** (`exact_match=true`, `raw_exact_match=true`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] client_session
[TARGET_FUNCTION] mk_pushover_notifier
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from asyncio import get_event_loop
from typing import Optional, List
import sys
from aiohttp import ClientSession
from dawg.notifier import Notifier
def mk_pushover_notifier(client_session: <mask>, api_key: str) -> Notifier:

    async def pushover_notify(username: str, message: str) -> Optional[Exception]:
        post_data = {'user': username, 'token': api_key, 'message': message}
        async with client_session.post(API_URL, data=post_data) as response:
            response_data = await response.json()
            print(response_data)
            return None
    return pushover_notify
mk_pushover_notifier(client_session, api_key)
notifier = mk_pushover_notifier(client_session, api_key)
post_data = {'user': username, 'token': api_key, 'message': message}
api_key = argv[1]
function mk_yo_notifier(client_session: ClientSession, api_key: str) -> Notifier
mk_pushover_notifier(client_session, api_token.token)
client_session = ClientSession()
notifier = mk_yo_notifier(client_session, api_token.token)
notifier = mk_pushover_notifier(client_session, api_token.token)
await client_session.close()
[RECOMMENDATION_TYPES]
[TYPE] ClientSession
[DEFINITION]
class ClientSession:
    # package: aiohttp
    # module: aiohttp.client
    # source: third_party
    # fields
    ATTRS = frozenset(['_base_url', '_base_url_origin', '_source_traceback', '_connector', '_loop', '_cookie_jar', '_connector_owner', '_default_auth', '_version', '_json_serialize', '_requote_redirect_url', '_timeout', '_raise_for_status', '_auto_decompress', '_trust_env', '_default_headers', '_skip_auto_headers', '_request_class', '_response_class', '_ws_response_class', '_trace_configs', '_read_bufsize', '_max_line_size', '_max_field_size', '_max_headers', '_resolve_charset', '_default_proxy', '_default_proxy_auth', '_retry_connection', '_middlewares', 'requote_redirect_url'])
    # public methods
    def __init__(self, base_url: Optional[StrOrURL]=None, *, connector: Optional[BaseConnector]=None, loop: Optional[asyncio.AbstractEventLoop]=None, cookies: Optional[LooseCookies]=None, headers: Optional[LooseHeaders]=None, proxy: Optional[StrOrURL]=None, proxy_auth: Optional[BasicAuth]=None, skip_auto_headers: Optional[Iterable[str]]=None, auth: Optional[BasicAuth]=None, json_serialize: JSONEncoder=json.dumps, request_class: Type[ClientRequest]=ClientRequest, response_class: Type[ClientResponse]=ClientResponse, ws_response_class: Type[ClientWebSocketResponse]=ClientWebSocketResponse, version: HttpVersion=http.HttpVersion11, cookie_jar: Optional[AbstractCookieJar]=None, connector_owner: bool=True, raise_for_status: Union[bool, Callable[[ClientResponse], Awaitable[None]]]=False, read_timeout: Union[float, _SENTINEL]=sentinel, conn_timeout: Optional[float]=None, timeout: Union[object, ClientTimeout]=sentinel, auto_decompress: bool=True, trust_env: bool=False, requote_redirect_url: bool=True, trace_configs: Optional[List[TraceConfig]]=None, read_bufsize: int=2 ** 16, max_line_size: int=8190, max_field_size: int=8190, max_headers: int=128, fallback_charset_resolver: _CharsetResolver=lambda r, b: 'utf-8', middlewares: Sequence[ClientMiddlewareType]=(), ssl_shutdown_timeout: Union[_SENTINEL, None, float]=sentinel) -> None:
    def ws_connect(self, url: StrOrURL, *, method: str=hdrs.METH_GET, protocols: Iterable[str]=(), timeout: Union[ClientWSTimeout, _SENTINEL]=sentinel, receive_timeout: Optional[float]=None, autoclose: bool=True, autoping: bool=True, heartbeat: Optional[float]=None, auth: Optional[BasicAuth]=None, origin: Optional[str]=None, params: Query=None, headers: Optional[LooseHeaders]=None, proxy: Optional[StrOrURL]=None, proxy_auth: Optional[BasicAuth]=None, ssl: Union[SSLContext, bool, Fingerprint]=True, verify_ssl: Optional[bool]=None, fingerprint: Optional[bytes]=None, ssl_context: Optional[SSLContext]=None, server_hostname: Optional[str]=None, proxy_headers: Optional[LooseHeaders]=None, compress: int=0, max_msg_size: int=4 * 1024 * 1024) -> '_WSRequestContextManager':
    async def close(self) -> None:
    def closed(self) -> bool:
    def connector(self) -> Optional[BaseConnector]:
    def cookie_jar(self) -> AbstractCookieJar:
    def version(self) -> Tuple[int, int]:
    def requote_redirect_url(self) -> bool:
    def requote_redirect_url(self, val: bool) -> None:
    def loop(self) -> asyncio.AbstractEventLoop:
    def timeout(self) -> ClientTimeout:
    def headers(self) -> 'CIMultiDict[str]':
    def skip_auto_headers(self) -> FrozenSet[istr]:
    def auth(self) -> Optional[BasicAuth]:
    def json_serialize(self) -> JSONEncoder:
    def connector_owner(self) -> bool:
    def raise_for_status(self) -> Union[bool, Callable[[ClientResponse], Awaitable[None]]]:
    def auto_decompress(self) -> bool:
    def trust_env(self) -> bool:
    def trace_configs(self) -> List[TraceConfig]:
    def detach(self) -> None:
    def __enter__(self) -> None:
    def __exit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]) -> None:
[TYPE] Response
[DEFINITION]
class Response(StreamResponse):
    # package: aiohttp
    # module: aiohttp.web_response
    # source: third_party
    # public methods
    def __init__(self, *, body: Any=None, status: int=200, reason: Optional[str]=None, text: Optional[str]=None, headers: Optional[LooseHeaders]=None, content_type: Optional[str]=None, charset: Optional[str]=None, zlib_executor_size: Optional[int]=None, zlib_executor: Optional[Executor]=None) -> None:
    def body(self) -> Optional[Union[bytes, Payload]]:
    def body(self, body: Any) -> None:
    def text(self) -> Optional[str]:
    def text(self, text: str) -> None:
    def content_length(self) -> Optional[int]:
    def content_length(self, value: Optional[int]) -> None:
    async def write_eof(self, data: bytes=b'') -> None:
[TYPE] _implementation
[DEFINITION]
@type_check_only
class _implementation:
    # package: sys
    # module: sys
    # source: typeshed
    # fields
    name: str
    version: _version_info
    hexversion: int
    cache_tag: str
[TYPE] _int_info
[DEFINITION]
@final
@type_check_only
class _int_info(structseq[int], tuple[int, int, int, int]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def bits_per_digit(self) -> int:
    def sizeof_digit(self) -> int:
    def default_max_str_digits(self) -> int:
    def str_digits_check_threshold(self) -> int:
[TYPE] _version_info
[DEFINITION]
@final
@type_check_only
class _version_info(_UninstantiableStructseq, tuple[int, int, int, _ReleaseLevel, int]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def major(self) -> int:
    def minor(self) -> int:
    def micro(self) -> int:
    def releaselevel(self) -> _ReleaseLevel:
    def serial(self) -> int:
[TYPE] _float_info
[DEFINITION]
@final
@type_check_only
class _float_info(structseq[float], tuple[float, int, int, float, int, int, int, int, float, int, int]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def max(self) -> float:
    def max_exp(self) -> int:
    def max_10_exp(self) -> int:
    def min(self) -> float:
    def min_exp(self) -> int:
    def min_10_exp(self) -> int:
    def dig(self) -> int:
    def mant_dig(self) -> int:
    def epsilon(self) -> float:
    def radix(self) -> int:
    def rounds(self) -> int:
[TYPE] _AsyncgenHook
[DEFINITION]
class _AsyncgenHook:
    # package: sys
    # module: sys
    # source: typeshed
    # kind: alias
    # type alias: Callable[[AsyncGenerator[Any, Any]], None] | None
[TYPE] _asyncgen_hooks
[DEFINITION]
@final
@type_check_only
class _asyncgen_hooks(structseq[_AsyncgenHook], tuple[_AsyncgenHook, _AsyncgenHook]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def firstiter(self) -> _AsyncgenHook:
    def finalizer(self) -> _AsyncgenHook:
[TYPE] _ReleaseLevel
[DEFINITION]
class _ReleaseLevel:
    # package: sys
    # module: sys
    # source: typeshed
    # kind: alias
    # type alias: Literal['alpha', 'beta', 'candidate', 'final']
[TYPE] _hash_info
[DEFINITION]
@final
@type_check_only
class _hash_info(structseq[Any | int], tuple[int, int, int, int, int, str, int, int, int]):
    # package: sys
    # module: sys
    # source: typeshed
    # public methods
    def width(self) -> int:
    def modulus(self) -> int:
    def inf(self) -> int:
    def nan(self) -> int:
    def imag(self) -> int:
    def algorithm(self) -> str:
    def hash_bits(self) -> int:
    def seed_bits(self) -> int:
    def cutoff(self) -> int:
```


## 5 ví dụ sai với kiểu user-defined/named

### Kiểu user-defined — sai 1: nhãn `Vector`, model dự đoán `List[float, int]`

- ID: `jwnwilson/python_types:repos/jwnwilson/python_types/main.py:34775:input_list`
- Project: `jwnwilson/python_types`
- Hàm đích: `expect_list`
- Phạm vi: `arg`
- Nhãn: `Vector`
- Dự đoán thô: `List[float, int]`
- Dự đoán chuẩn hóa: `List[float, int]`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] input_list
[TARGET_FUNCTION] expect_list
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from typing import List
from typing import Mapping
from typing import Sequence
def expect_list(input_list: <mask>) -> float:
    """return the sum of a list of floats or ints

    :param input_list: list of floats or ints
    """
    return sum(input_list)
expect_list([1, 0.2, 0.5])
[RECOMMENDATION_TYPES]
[TYPE] Mapping
[DEFINITION]
class Mapping(Collection[_KT], Generic[_KT, _VT_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, key: _KT, /) -> _VT_co:
    def get(self, key: _KT, /) -> _VT_co | None:
    def get(self, key: _KT, default: _VT_co, /) -> _VT_co:
    def get(self, key: _KT, default: _T, /) -> _VT_co | _T:
    def items(self) -> ItemsView[_KT, _VT_co]:
    def keys(self) -> KeysView[_KT]:
    def values(self) -> ValuesView[_VT_co]:
[TYPE] Sequence
[DEFINITION]
class Sequence(Reversible[_T_co], Collection[_T_co]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, index: int, /) -> _T_co:
    def __getitem__(self, index: slice[int | None], /) -> Sequence[_T_co]:
    def index(self, value: Any, start: int=0, stop: int=..., /) -> int:
    def count(self, value: Any, /) -> int:
    def __iter__(self) -> Iterator[_T_co]:
[TYPE] User
[DEFINITION]
class User:
    def __str__(self):
        return 'User instance!'
[TYPE] _P
[DEFINITION]
class _P:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: ParamSpec('_P')
[TYPE] _S
[DEFINITION]
class _S:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('_S')
[TYPE] _T
[DEFINITION]
class _T:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('_T')
[TYPE] MutableSet
[DEFINITION]
class MutableSet(AbstractSet[_T]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def add(self, value: _T, /) -> None:
    def discard(self, value: _T, /) -> None:
    def clear(self) -> None:
    def pop(self) -> _T:
    def remove(self, value: _T, /) -> None:
[TYPE] _Alias
[DEFINITION]
@type_check_only
class _Alias:
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def __getitem__(self, typeargs: Any) -> Any:
[TYPE] _Final
[DEFINITION]
class _Final:
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] AnyStr
[DEFINITION]
class AnyStr:
    # package: typing
    # module: typing
    # source: typeshed
    # kind: alias
    # type alias: TypeVar('AnyStr', str, bytes)
```

### Kiểu user-defined — sai 2: nhãn `JsonDict`, model dự đoán `List[str]`

- ID: `MGodgildieva/allennlp_NLP_hw4:repos/MGodgildieva/allennlp_NLP_hw4/library/predictor/predictor.py:6750:predict_json`
- Project: `MGodgildieva/allennlp_NLP_hw4`
- Hàm đích: `LngPredictor.predict_json`
- Phạm vi: `return`
- Nhãn: `JsonDict`
- Dự đoán thô: `List[str]`
- Dự đoán chuẩn hóa: `List[str]`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] predict_json
[TARGET_FUNCTION] LngPredictor.predict_json
[TARGET_SCOPE] return
[INTERPROCEDURAL_SLICE]
from allennlp.predictors import Predictor
from allennlp.common.util import JsonDict
import numpy as np
function text_to_instance(self, names: List[str], categories: List[str] = None) -> Instance
def argmax(a: ArrayLike, axis: None=..., out: None=..., *, keepdims: Literal[False]=...) -> intp:
def predict_json(self, inputs: JsonDict) -> <mask>:
    instance = self._dataset_reader.text_to_instance(inputs)
    output_dict = self.predict_instance(instance)
    tag_ids = np.argmax(output_dict['logits'], axis=-1)
    return [self._model.vocab.get_token_from_index(i, 'labels') for i in tag_ids]
[RECOMMENDATION_TYPES]
[TYPE] Predictor
[DEFINITION]
class Predictor(Registrable):
    # package: allennlp
    # module: allennlp.predictors.predictor
    # source: third_party
    # public methods
    def __init__(self, model: Model, dataset_reader: DatasetReader, frozen: bool=True) -> None:
    def load_line(self, line: str) -> JsonDict:
    def dump_line(self, outputs: JsonDict) -> str:
    def predict_json(self, inputs: JsonDict) -> ((<mask>)):
    def json_to_labeled_instances(self, inputs: JsonDict) -> List[Instance]:
    def get_gradients(self, instances: List[Instance]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    def get_interpretable_layer(self) -> torch.nn.Module:
    def get_interpretable_text_field_embedder(self) -> torch.nn.Module:
    def capture_model_internals(self, module_regex: str='.*') -> Iterator[dict]:
    def predict_instance(self, instance: Instance) -> JsonDict:
    def predictions_to_labeled_instances(self, instance: Instance, outputs: Dict[str, numpy.ndarray]) -> List[Instance]:
    def predict_batch_json(self, inputs: List[JsonDict]) -> List[JsonDict]:
    def predict_batch_instance(self, instances: List[Instance]) -> List[JsonDict]:
    def from_path(cls, archive_path: Union[str, PathLike], predictor_name: str=None, cuda_device: int=-1, dataset_reader_to_load: str='validation', frozen: bool=True, import_plugins: bool=True, overrides: Union[str, Dict[str, Any]]='', **kwargs) -> 'Predictor':
    def from_archive(cls, archive: Archive, predictor_name: str=None, dataset_reader_to_load: str='validation', frozen: bool=True, extra_args: Optional[Dict[str, Any]]=None) -> 'Predictor':
[TYPE] Instance
[DEFINITION]
class Instance(Mapping[str, Field]):
    # package: allennlp
    # module: allennlp.data.instance
    # source: third_party
    # public methods
    def __init__(self, fields: MutableMapping[str, Field]) -> None:
    def __getitem__(self, key: str) -> Field:
    def __iter__(self):
    def __len__(self) -> int:
    def add_field(self, field_name: str, field: Field, vocab: Vocabulary=None) -> None:
    def count_vocab_items(self, counter: Dict[str, Dict[str, int]]):
    def index_fields(self, vocab: Vocabulary) -> None:
    def get_padding_lengths(self) -> Dict[str, Dict[str, int]]:
    def as_tensor_dict(self, padding_lengths: Dict[str, Dict[str, int]]=None) -> Dict[str, DataArray]:
    def duplicate(self) -> 'Instance':
    def human_readable_dict(self) -> JsonDict:
[TYPE] JsonDict
[DEFINITION]
class JsonDict:
    # package: allennlp
    # module: allennlp.common.util
    # source: third_party
    # kind: alias
    # type alias: Dict[str, Any]
[TYPE] ArrayLike
[DEFINITION]
class ArrayLike(np.lib.mixins.NDArrayOperatorsMixin):
    # package: numpy
    # module: numpy.lib.tests.test_mixins
    # source: third_party
    # public methods
    def __init__(self, value):
[TYPE] For
[DEFINITION]
class For(Stmt):
    # package: torch
    # module: torch._C._jit_tree_views
    # source: third_party
    # public methods
    def __init__(self, range: SourceRange, targets: list[Expr], itrs: list[Expr], body: list[Stmt]) -> None:
[TYPE] A
[DEFINITION]
class A:
    # package: allennlp
    # module: allennlp.common.util
    # source: third_party
    # kind: alias
    # type alias: TypeVar('A')
[TYPE] Def
[DEFINITION]
class Def(TreeView):
    # package: torch
    # module: torch._C._jit_tree_views
    # source: third_party
    # public methods
    def __init__(self, name: Ident, decl: Any, body: list[Stmt]) -> None:
    def decl(self) -> Any:
    def name(self) -> Ident:
[TYPE] Return
[DEFINITION]
class Return(Stmt):
    # package: torch
    # module: torch._C._jit_tree_views
    # source: third_party
    # public methods
    def __init__(self, range: SourceRange, value: Optional[Expr]) -> None:
[TYPE] Function
[DEFINITION]
class Function(_SingleLevelFunction):
    # package: torch
    # module: torch.autograd.function
    # source: third_party
    # fields
    generate_vmap_rule = False
    # public methods
    def __init__(self, *args, **kwargs):
    def __call__(self, *args, **kwargs):
    def vmap(info, in_dims, *args):
    def apply(cls, *args, **kwargs):
[TYPE] Names
[DEFINITION]
class Names:
    # package: torch
    # module: torch.fx.passes.tools_common
    # source: third_party
    # kind: alias
    # type alias: list[str]
```

### Kiểu user-defined — sai 3: nhãn `ImageSequenceClip`, model dự đoán `VideoClip`

- ID: `umutseven92/LaFontaine:repos/umutseven92/LaFontaine/lafontaine/generator/video_generator.py:51017:_generate_from_scene`
- Project: `umutseven92/LaFontaine`
- Hàm đích: `VideoGenerator._generate_from_scene`
- Phạm vi: `return`
- Nhãn: `ImageSequenceClip`
- Dự đoán thô: `VideoClip`
- Dự đoán chuẩn hóa: `VideoClip`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] _generate_from_scene
[TARGET_FUNCTION] VideoGenerator._generate_from_scene
[TARGET_SCOPE] return
[INTERPROCEDURAL_SLICE]
import os
from datetime import timedelta
from typing import List
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.editor import concatenate_videoclips
from moviepy.video.VideoClip import TextClip
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip
from lafontaine.helpers.frame import Frame
from lafontaine.helpers.scene import Scene
function _generate_from_frames(self, frames: List[Frame], fps)
def _generate_from_scene(self, scene, fps) -> <mask>:
    return self._generate_from_frames(scene.frames, fps)
self._generate_from_scene(scene, fps)
clip = self._generate_from_scene(scene, fps)
return self._generate_from_frames(scene.frames, fps)
clip = ImageSequenceClip(images, fps=fps)
[RECOMMENDATION_TYPES]
[TYPE] Scene
[DEFINITION]
class Scene:
    def __init__(self):
        self.frames = []

    def add_frame(self, frame):
        self.frames.append(frame)

    def add_frames(self, frames):
        self.frames.extend(frames)

    def start_ts(self):
        return self.frames[0].timestamp

    def end_ts(self):
        return self.frames[-1].timestamp
[TYPE] ImageSequenceClip
[DEFINITION]
class ImageSequenceClip(VideoClip):
    # package: moviepy
    # module: moviepy.video.io.ImageSequenceClip
    # source: third_party
    # public methods
    def __init__(self, sequence, fps=None, durations=None, with_mask=True, ismask=False, load_images=False):
[TYPE] VideoClip
[DEFINITION]
class VideoClip(Clip):
    # package: moviepy
    # module: moviepy.video.VideoClip
    # source: third_party
    # public methods
    def __init__(self, make_frame=None, ismask=False, duration=None, has_constant_size=True):
    def w(self):
    def h(self):
    def aspect_ratio(self):
    def save_frame(self, filename, t=0, withmask=True):
    def write_videofile(self, filename, fps=None, codec=None, bitrate=None, audio=True, audio_fps=44100, preset='medium', audio_nbytes=4, audio_codec=None, audio_bitrate=None, audio_bufsize=2000, temp_audiofile=None, rewrite_audio=True, remove_temp=True, write_logfile=False, verbose=True, threads=None, ffmpeg_params=None, logger='bar'):
    def write_images_sequence(self, nameformat, fps=None, verbose=True, withmask=True, logger='bar'):
    def write_gif(self, filename, fps=None, program='imageio', opt='nq', fuzz=1, verbose=True, loop=0, dispose=False, colors=None, tempfiles=False, logger='bar'):
    def subfx(self, fx, ta=0, tb=None, **kwargs):
    def fl_image(self, image_func, apply_to=None):
    def fill_array(self, pre_array, shape=(0, 0)):
    def blit_on(self, picture, t):
    def add_mask(self):
    def on_color(self, size=None, color=(0, 0, 0), pos=None, col_opacity=None):
    def set_make_frame(self, mf):
    def set_audio(self, audioclip):
    def set_mask(self, mask):
    def set_opacity(self, op):
    def set_position(self, pos, relative=False):
    def to_ImageClip(self, t=0, with_mask=True, duration=None):
    def to_mask(self, canal=0):
    def to_RGB(self):
    def without_audio(self):
    def afx(self, fun, *a, **k):
[TYPE] AudioFileClip
[DEFINITION]
class AudioFileClip(AudioClip):
    # package: moviepy
    # module: moviepy.audio.io.AudioFileClip
    # source: third_party
    # public methods
    def __init__(self, filename, buffersize=200000, nbytes=2, fps=44100):
    def coreader(self):
    def close(self):
[TYPE] TextClip
[DEFINITION]
class TextClip(ImageClip):
    # package: moviepy
    # module: moviepy.video.VideoClip
    # source: third_party
    # public methods
    def __init__(self, txt=None, filename=None, size=None, color='black', bg_color='transparent', fontsize=None, font='Courier', stroke_color=None, stroke_width=1, method='label', kerning=None, align='center', interline=None, tempfilename=None, temptxt=None, transparent=True, remove_temp=True, print_cmd=False):
    def list(arg):
    def search(string, arg):
[TYPE] Frame
[DEFINITION]
class Frame:
    def __init__(self, image, audio, timestamp, sub: SubRipItem = None):
        self.image = image
        self.audio = audio
        self.timestamp = timestamp
        self.sub = sub
[TYPE] Clip
[DEFINITION]
class Clip:
    # package: moviepy
    # module: moviepy.Clip
    # source: third_party
    # public methods
    def __init__(self):
    def copy(self):
    def get_frame(self, t):
    def fl(self, fun, apply_to=None, keep_duration=True):
    def fl_time(self, t_func, apply_to=None, keep_duration=False):
    def fx(self, func, *args, **kwargs):
    def set_start(self, t, change_end=True):
    def set_end(self, t):
    def set_duration(self, t, change_end=True):
    def set_make_frame(self, make_frame):
    def set_fps(self, fps):
    def set_ismask(self, ismask):
    def set_memoize(self, memoize):
    def is_playing(self, t):
    def subclip(self, t_start=0, t_end=None):
    def cutout(self, ta, tb):
    def iter_frames(self, fps=None, with_times=False, logger=None, dtype=None):
    def close(self):
    def __enter__(self):
    def __exit__(self, exc_type, exc_value, traceback):
[TYPE] IO
[DEFINITION]
class IO(Generic[AnyStr]):
    # package: typing
    # module: typing
    # source: typeshed
    # public methods
    def mode(self) -> str:
    def name(self) -> str | Any:
    def close(self) -> None:
    def closed(self) -> bool:
    def fileno(self) -> int:
    def flush(self) -> None:
    def isatty(self) -> bool:
    def read(self, n: int=-1, /) -> AnyStr:
    def readable(self) -> bool:
    def readline(self, limit: int=-1, /) -> AnyStr:
    def readlines(self, hint: int=-1, /) -> list[AnyStr]:
    def seek(self, offset: int, whence: int=0, /) -> int:
    def seekable(self) -> bool:
    def tell(self) -> int:
    def truncate(self, size: int | None=None, /) -> int:
    def writable(self) -> bool:
    def write(self: IO[bytes], s: ReadableBuffer, /) -> int:
    def write(self, s: AnyStr, /) -> int:
    def writelines(self: IO[bytes], lines: Iterable[ReadableBuffer], /) -> None:
    def writelines(self, lines: Iterable[AnyStr], /) -> None:
    def __iter__(self) -> Iterator[AnyStr]:
    def __enter__(self) -> IO[AnyStr]:
    def __exit__(self, type: type[BaseException] | None, value: BaseException | None, traceback: TracebackType | None, /) -> None:
[TYPE] datetime
[DEFINITION]
@disjoint_base
class datetime(date):
    # package: datetime
    # module: datetime
    # source: typeshed
    # fields
    min: ClassVar[datetime]
    max: ClassVar[datetime]
    # public methods
    def hour(self) -> int:
    def minute(self) -> int:
    def second(self) -> int:
    def microsecond(self) -> int:
    def tzinfo(self) -> _TzInfo | None:
    def fold(self) -> int:
    def utcfromtimestamp(cls, t: float, /) -> Self:
    def now(cls, tz: _TzInfo | None=None) -> Self:
    def utcnow(cls) -> Self:
    def combine(cls, date: _Date, time: _Time, tzinfo: _TzInfo | None=...) -> Self:
    def timestamp(self) -> float:
    def utctimetuple(self) -> struct_time:
    def date(self) -> _Date:
    def time(self) -> _Time:
    def timetz(self) -> _Time:
    def replace(self, year: SupportsIndex=..., month: SupportsIndex=..., day: SupportsIndex=..., hour: SupportsIndex=..., minute: SupportsIndex=..., second: SupportsIndex=..., microsecond: SupportsIndex=..., tzinfo: _TzInfo | None=..., *, fold: int=...) -> Self:
    def astimezone(self, tz: _TzInfo | None=None) -> Self:
    def isoformat(self, sep: str='T', timespec: str='auto') -> str:
    def utcoffset(self) -> timedelta | None:
    def tzname(self) -> str | None:
    def dst(self) -> timedelta | None:
[TYPE] timedelta
[DEFINITION]
@disjoint_base
class timedelta:
    # package: datetime
    # module: datetime
    # source: typeshed
    # fields
    min: ClassVar[timedelta]
    max: ClassVar[timedelta]
    resolution: ClassVar[timedelta]
    # public methods
    def days(self) -> int:
    def seconds(self) -> int:
    def microseconds(self) -> int:
    def total_seconds(self) -> float:
```

### Kiểu user-defined — sai 4: nhãn `FunctionArgs`, model dự đoán `Tuple[Any]`

- ID: `ekisu/dots:repos/ekisu/dots/dots/cli.py:26259:output_args`
- Project: `ekisu/dots`
- Hàm đích: `main`
- Phạm vi: `arg`
- Nhãn: `FunctionArgs`
- Dự đoán thô: `Tuple[Any]`
- Dự đoán chuẩn hóa: `Tuple[Any]`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] output_args
[TARGET_FUNCTION] main
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from .image import ImageLoader
from .threshold import threshold_function
from .output import output_function
from argparse import ArgumentParser
from typing import Callable, Any, List, Dict, Tuple
from pathlib import Path
from ast import literal_eval
import numpy as np
def main(image_path: Path, resize_factor: float, threshold: Callable[..., Any], threshold_args: FunctionArgs, invert: bool, no_transparency_mask: bool, output: Callable[..., List[str]], output_args: <mask>):
    loader = ImageLoader.from_path(image_path)
    loader.resize_with_factor(resize_factor)
    grayscale_image = loader.as_grayscale()
    transparency_mask = loader.transparency_mask()
    t_args, t_kwargs = threshold_args
    binary_matrix = threshold(grayscale_image, *t_args, **t_kwargs)
    if invert:
        binary_matrix = np.invert(binary_matrix)
    if not no_transparency_mask:
        binary_matrix = np.logical_and(binary_matrix, np.invert(transparency_mask))
    o_args, o_kwargs = output_args
    lines = output(binary_matrix, *o_args, **o_kwargs)
    print('\n'.join(lines))
main(**vars(args))
unittest.main()
[RECOMMENDATION_TYPES]
[TYPE] ArgumentParser
[DEFINITION]
class ArgumentParser(_AttributeHolder, _ActionsContainer):
    # package: argparse
    # module: argparse
    # source: typeshed
    # fields
    prog: str
    usage: str | None
    epilog: str | None
    formatter_class: _FormatterClass
    fromfile_prefix_chars: str | None
    add_help: bool
    allow_abbrev: bool
    exit_on_error: bool
    # public methods
    def parse_args(self, args: Iterable[str] | None=None, namespace: None=None) -> Namespace:
    def parse_args(self, args: Iterable[str] | None, namespace: _N) -> _N:
    def parse_args(self, *, namespace: _N) -> _N:
    def add_subparsers(self: _ArgumentParserT, *, title: str='subcommands', description: str | None=None, prog: str | None=None, action: type[Action]=..., option_string: str=..., dest: str | None=None, required: bool=False, help: str | None=None, metavar: str | None=None) -> _SubParsersAction[_ArgumentParserT]:
    def add_subparsers(self, *, title: str='subcommands', description: str | None=None, prog: str | None=None, parser_class: type[_ArgumentParserT], action: type[Action]=..., option_string: str=..., dest: str | None=None, required: bool=False, help: str | None=None, metavar: str | None=None) -> _SubParsersAction[_ArgumentParserT]:
    def print_usage(self, file: SupportsWrite[str] | None=None) -> None:
    def print_help(self, file: SupportsWrite[str] | None=None) -> None:
    def parse_known_args(self, args: Iterable[str] | None=None, namespace: None=None) -> tuple[Namespace, list[str]]:
    def parse_known_args(self, args: Iterable[str] | None, namespace: _N) -> tuple[_N, list[str]]:
    def parse_known_args(self, *, namespace: _N) -> tuple[_N, list[str]]:
    def convert_arg_line_to_args(self, arg_line: str) -> list[str]:
    def exit(self, status: int=0, message: str | None=None) -> Never:
    def error(self, message: str) -> Never:
    def parse_intermixed_args(self, args: Iterable[str] | None=None, namespace: None=None) -> Namespace:
    def parse_intermixed_args(self, args: Iterable[str] | None, namespace: _N) -> _N:
    def parse_intermixed_args(self, *, namespace: _N) -> _N:
    def parse_known_intermixed_args(self, args: Iterable[str] | None=None, namespace: None=None) -> tuple[Namespace, list[str]]:
    def parse_known_intermixed_args(self, args: Iterable[str] | None, namespace: _N) -> tuple[_N, list[str]]:
    def parse_known_intermixed_args(self, *, namespace: _N) -> tuple[_N, list[str]]:
[TYPE] ImageLoader
[DEFINITION]
class ImageLoader(object):
    def __init__(self, image):
        if isinstance(image, type(None)):
            raise RuntimeError("image == None")
        self.image: Any = image

    @classmethod
    def from_path(cls, path: Path) -> 'ImageLoader':
        image = cv2.imread(path.resolve().as_posix(), cv2.IMREAD_UNCHANGED)
        return cls(image)

    @classmethod
    def from_bytes(cls, bytes_: bytes) -> 'ImageLoader':
        data_array = np.asarray(bytearray(bytes_), dtype=np.uint8)
        try:
            image = cv2.imdecode(data_array, cv2.IMREAD_UNCHANGED)
            return cls(image)
        except cv2.error:
            raise RuntimeError("Failed to decode bytes")

    def resize_with_factor(self, factor: float):
        if factor == 1:
            return
        self.image = cv2.resize(self.image, None, fx=factor, fy=factor)

    def as_grayscale(self):
        return cv2.cvtColor(self.image, cv2.COLOR_RGB2GRAY)

    def transparency_mask(self, transparency_threshold: int = 127):
        w, h, channels = self.image.shape
        if channels < 4:  # No alpha channel?
            return np.full((w, h), True)

        return self.image[:, :, 3] < transparency_threshold
[TYPE] Path
[DEFINITION]
class Path(PurePath):
    # package: pathlib
    # module: pathlib
    # source: typeshed
    # public methods
    def cwd(cls) -> Self:
    def stat(self, *, follow_symlinks: bool=True) -> stat_result:
    def chmod(self, mode: int, *, follow_symlinks: bool=True) -> None:
    def is_symlink(self) -> bool:
    def is_socket(self) -> bool:
    def is_fifo(self) -> bool:
    def is_block_device(self) -> bool:
    def is_char_device(self) -> bool:
    def iterdir(self) -> Generator[Self]:
    def lchmod(self, mode: int) -> None:
    def lstat(self) -> stat_result:
    def open(self, mode: OpenTextMode='r', buffering: int=-1, encoding: str | None=None, errors: str | None=None, newline: str | None=None) -> TextIOWrapper:
    def open(self, mode: OpenBinaryMode, buffering: Literal[0], encoding: None=None, errors: None=None, newline: None=None) -> FileIO:
    def open(self, mode: OpenBinaryModeUpdating, buffering: Literal[-1, 1]=-1, encoding: None=None, errors: None=None, newline: None=None) -> BufferedRandom:
    def open(self, mode: OpenBinaryModeWriting, buffering: Literal[-1, 1]=-1, encoding: None=None, errors: None=None, newline: None=None) -> BufferedWriter:
    def open(self, mode: OpenBinaryModeReading, buffering: Literal[-1, 1]=-1, encoding: None=None, errors: None=None, newline: None=None) -> BufferedReader:
    def open(self, mode: OpenBinaryMode, buffering: int=-1, encoding: None=None, errors: None=None, newline: None=None) -> BinaryIO:
    def open(self, mode: str, buffering: int=-1, encoding: str | None=None, errors: str | None=None, newline: str | None=None) -> IO[Any]:
    def readlink(self) -> Self:
    def rename(self, target: StrPath) -> Self:
    def replace(self, target: StrPath) -> Self:
    def resolve(self, strict: bool=False) -> Self:
    def rmdir(self) -> None:
    def symlink_to(self, target: StrOrBytesPath, target_is_directory: bool=False) -> None:
    def hardlink_to(self, target: StrOrBytesPath) -> None:
    def touch(self, mode: int=438, exist_ok: bool=True) -> None:
    def unlink(self, missing_ok: bool=False) -> None:
    def home(cls) -> Self:
    def absolute(self) -> Self:
    def expanduser(self) -> Self:
    def read_bytes(self) -> bytes:
    def samefile(self, other_path: StrPath) -> bool:
    def write_bytes(self, data: ReadableBuffer) -> int:
    def write_text(self, data: str, encoding: str | None=None, errors: str | None=None, newline: str | None=None) -> int:
    def as_uri(self) -> str:
[TYPE] Any
[DEFINITION]
class Any:
    # package: typing
    # module: typing
    # source: typeshed
    pass
[TYPE] Dict
[DEFINITION]
class Dict(expr):
    # package: ast
    # module: ast
    # source: typeshed
    # fields
    keys: list[expr | None]
    values: list[expr]
[TYPE] List
[DEFINITION]
class List(expr):
    # package: ast
    # module: ast
    # source: typeshed
    # fields
    elts: list[expr]
    ctx: expr_context
[TYPE] Tuple
[DEFINITION]
class Tuple(expr):
    # package: ast
    # module: ast
    # source: typeshed
    # fields
    elts: list[expr]
    ctx: expr_context
    dims: list[expr]
[TYPE] Invert
[DEFINITION]
class Invert(unaryop):
    # package: ast
    # module: ast
    # source: typeshed
    pass
[TYPE] bool
[DEFINITION]
class bool(generic):
    # package: numpy
    # module: numpy
    # source: third_party
    # public methods
    def __init__(self, value: object=..., /) -> None:
    def item(self, args: L[0] | tuple[()] | tuple[L[0]]=..., /) -> builtins.bool:
    def tolist(self) -> builtins.bool:
    def real(self: _ArraySelf) -> _ArraySelf:
    def imag(self: _ArraySelf) -> _ArraySelf:
[TYPE] _FlatIterSelf
[DEFINITION]
class _FlatIterSelf:
    # package: numpy
    # module: numpy
    # source: third_party
    # kind: alias
    # type alias: TypeVar('_FlatIterSelf', bound=flatiter[Any])
```

### Kiểu user-defined — sai 5: nhãn `DatabaseSchemaEditor`, model dự đoán `BaseDatabaseSchemaEditor`

- ID: `zulip/zulip:repos/zulip/zulip/zerver/migrations/0247_realmauditlog_event_type_to_int.py:51778:schema_editor`
- Project: `zulip/zulip`
- Hàm đích: `reverse_code`
- Phạm vi: `arg`
- Nhãn: `DatabaseSchemaEditor`
- Dự đoán thô: `BaseDatabaseSchemaEditor`
- Dự đoán chuẩn hóa: `BaseDatabaseSchemaEditor`
- Kết quả: **sai** (`exact_match=false`, `raw_exact_match=false`)

Input đầy đủ từ Dataset v15:

```text
[TARGET_NAME] schema_editor
[TARGET_FUNCTION] reverse_code
[TARGET_SCOPE] arg
[INTERPROCEDURAL_SLICE]
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
def reverse_code(apps: StateApps, schema_editor: <mask>) -> None:
    RealmAuditLog = apps.get_model('zerver', 'RealmAuditLog')
    for log_entry in RealmAuditLog.objects.all().iterator():
        log_entry.event_type = STR_VALUE[log_entry.event_type_int]
        log_entry.save(update_fields=['event_type'])
[RECOMMENDATION_TYPES]
[TYPE] BaseDatabaseSchemaEditor
[DEFINITION]
class BaseDatabaseSchemaEditor:
    # package: django
    # module: django.db.backends.base.schema
    # source: third_party
    # fields
    sql_create_table = 'CREATE TABLE %(table)s (%(definition)s)'
    sql_rename_table = 'ALTER TABLE %(old_table)s RENAME TO %(new_table)s'
    sql_retablespace_table = 'ALTER TABLE %(table)s SET TABLESPACE %(new_tablespace)s'
    sql_delete_table = 'DROP TABLE %(table)s CASCADE'
    sql_create_column = 'ALTER TABLE %(table)s ADD COLUMN %(column)s %(definition)s'
    sql_alter_column = 'ALTER TABLE %(table)s %(changes)s'
    sql_alter_column_type = 'ALTER COLUMN %(column)s TYPE %(type)s%(collation)s'
    sql_alter_column_null = 'ALTER COLUMN %(column)s DROP NOT NULL'
    sql_alter_column_not_null = 'ALTER COLUMN %(column)s SET NOT NULL'
    sql_alter_column_default = 'ALTER COLUMN %(column)s SET DEFAULT %(default)s'
    sql_alter_column_no_default = 'ALTER COLUMN %(column)s DROP DEFAULT'
    sql_alter_column_no_default_null = sql_alter_column_no_default
    sql_delete_column = 'ALTER TABLE %(table)s DROP COLUMN %(column)s'
    sql_rename_column = 'ALTER TABLE %(table)s RENAME COLUMN %(old_column)s TO %(new_column)s'
    sql_update_with_default = 'UPDATE %(table)s SET %(column)s = %(default)s WHERE %(column)s IS NULL'
    sql_unique_constraint = 'UNIQUE (%(columns)s)%(deferrable)s'
    sql_check_constraint = 'CHECK (%(check)s)'
    sql_delete_constraint = 'ALTER TABLE %(table)s DROP CONSTRAINT %(name)s'
    sql_constraint = 'CONSTRAINT %(name)s %(constraint)s'
    sql_pk_constraint = 'PRIMARY KEY (%(columns)s)'
    sql_create_check = 'ALTER TABLE %(table)s ADD CONSTRAINT %(name)s CHECK (%(check)s)'
    sql_delete_check = sql_delete_constraint
    sql_create_unique = 'ALTER TABLE %(table)s ADD CONSTRAINT %(name)s UNIQUE%(nulls_distinct)s (%(columns)s)%(deferrable)s'
    sql_delete_unique = sql_delete_constraint
    sql_create_fk = 'ALTER TABLE %(table)s ADD CONSTRAINT %(name)s FOREIGN KEY (%(column)s) REFERENCES %(to_table)s (%(to_column)s)%(on_delete_db)s%(deferrable)s'
    sql_create_inline_fk = None
    sql_create_column_inline_fk = None
    sql_delete_fk = sql_delete_constraint
    sql_create_index = 'CREATE INDEX %(name)s ON %(table)s (%(columns)s)%(include)s%(extra)s%(condition)s'
    sql_create_unique_index = 'CREATE UNIQUE INDEX %(name)s ON %(table)s (%(columns)s)%(include)s%(nulls_distinct)s%(condition)s'
    sql_rename_index = 'ALTER INDEX %(old_name)s RENAME TO %(new_name)s'
    sql_delete_index = 'DROP INDEX %(name)s'
    sql_create_pk = 'ALTER TABLE %(table)s ADD CONSTRAINT %(name)s PRIMARY KEY (%(columns)s)'
    sql_delete_pk = sql_delete_constraint
    sql_delete_procedure = 'DROP PROCEDURE %(procedure)s'
    sql_alter_table_comment = 'COMMENT ON TABLE %(table)s IS %(comment)s'
    sql_alter_column_comment = 'COMMENT ON COLUMN %(table)s.%(column)s IS %(comment)s'
    # public methods
    def __init__(self, connection, collect_sql=False, atomic=True):
    def __enter__(self):
    def __exit__(self, exc_type, exc_value, traceback):
    def execute(self, sql, params=()):
    def quote_name(self, name):
    def table_sql(self, model):
    def column_sql(self, model, field, include_default=False):
    def skip_default(self, field):
    def skip_default_on_alter(self, field):
    def prepare_default(self, value):
    def db_default_sql(self, field):
    def effective_default(self, field):
    def quote_value(self, value):
    def create_model(self, model):
    def delete_model(self, model):
    def add_index(self, model, index):
    def remove_index(self, model, index):
    def rename_index(self, model, old_index, new_index):
    def add_constraint(self, model, constraint):
    def remove_constraint(self, model, constraint):
    def alter_unique_together(self, model, old_unique_together, new_unique_together):
    def alter_index_together(self, model, old_index_together, new_index_together):
    def alter_db_table(self, model, old_db_table, new_db_table):
    def alter_db_table_comment(self, model, old_db_table_comment, new_db_table_comment):
    def alter_db_tablespace(self, model, old_db_tablespace, new_db_tablespace):
    def add_field(self, model, field):
    def remove_field(self, model, field):
    def alter_field(self, model, old_field, new_field, strict=False):
    def remove_procedure(self, procedure_name, param_types=()):
[TYPE] StateApps
[DEFINITION]
class StateApps(Apps):
    # package: django
    # module: django.db.migrations.state
    # source: third_party
    # public methods
    def __init__(self, real_apps, models, ignore_swappable=False):
    def bulk_update(self):
    def render_multiple(self, model_states):
    def clone(self):
    def register_model(self, app_label, model):
    def unregister_model(self, app_label, model_name):
[TYPE] Models
[DEFINITION]
class Models(SyncAPIResource):
    # package: openai
    # module: openai.resources.models
    # source: third_party
    # public methods
    def with_raw_response(self) -> ModelsWithRawResponse:
    def with_streaming_response(self) -> ModelsWithStreamingResponse:
    def retrieve(self, model: str, *, extra_headers: Headers | None=None, extra_query: Query | None=None, extra_body: Body | None=None, timeout: float | httpx.Timeout | None | NotGiven=not_given) -> Model:
    def list(self, *, extra_headers: Headers | None=None, extra_query: Query | None=None, extra_body: Body | None=None, timeout: float | httpx.Timeout | None | NotGiven=not_given) -> SyncPage[Model]:
    def delete(self, model: str, *, extra_headers: Headers | None=None, extra_query: Query | None=None, extra_body: Body | None=None, timeout: float | httpx.Timeout | None | NotGiven=not_given) -> ModelDeleted:
[TYPE] Migration
[DEFINITION]
class Migration:
    # package: django
    # module: django.db.migrations.migration
    # source: third_party
    # fields
    operations = []
    dependencies = []
    run_before = []
    replaces = []
    initial = None
    atomic = True
    # public methods
    def __init__(self, name, app_label):
    def mutate_state(self, project_state, preserve=True):
    def apply(self, project_state, schema_editor, collect_sql=False):
    def unapply(self, project_state, schema_editor, collect_sql=False):
    def suggest_name(self):
[TYPE] RunPython
[DEFINITION]
class RunPython(Operation):
    # package: django
    # module: django.db.migrations.operations.special
    # source: third_party
    # fields
    category = OperationCategory.PYTHON
    reduces_to_sql = False
    # public methods
    def __init__(self, code, reverse_code=None, atomic=None, hints=None, elidable=False):
    def deconstruct(self):
    def reversible(self):
    def state_forwards(self, app_label, state):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
    def database_backwards(self, app_label, schema_editor, from_state, to_state):
    def describe(self):
    def noop(apps, schema_editor):
[TYPE] MySQLGISSchemaEditor
[DEFINITION]
class MySQLGISSchemaEditor(DatabaseSchemaEditor):
    # package: django
    # module: django.contrib.gis.db.backends.mysql.schema
    # source: third_party
    # fields
    sql_add_spatial_index = 'CREATE SPATIAL INDEX %(index)s ON %(table)s(%(column)s)'
    # public methods
    def quote_value(self, value):
    def remove_field(self, model, field):
[TYPE] OracleGISSchemaEditor
[DEFINITION]
class OracleGISSchemaEditor(DatabaseSchemaEditor):
    # package: django
    # module: django.contrib.gis.db.backends.oracle.schema
    # source: third_party
    # fields
    sql_add_geometry_metadata = '\n        INSERT INTO USER_SDO_GEOM_METADATA\n            ("TABLE_NAME", "COLUMN_NAME", "DIMINFO", "SRID")\n        VALUES (\n            %(table)s,\n            %(column)s,\n            MDSYS.SDO_DIM_ARRAY(\n                MDSYS.SDO_DIM_ELEMENT(\'LONG\', %(dim0)s, %(dim2)s, %(tolerance)s),\n                MDSYS.SDO_DIM_ELEMENT(\'LAT\', %(dim1)s, %(dim3)s, %(tolerance)s)\n            ),\n            %(srid)s\n        )'
    sql_add_spatial_index = 'CREATE INDEX %(index)s ON %(table)s(%(column)s) INDEXTYPE IS MDSYS.SPATIAL_INDEX'
    sql_clear_geometry_table_metadata = 'DELETE FROM USER_SDO_GEOM_METADATA WHERE TABLE_NAME = %(table)s'
    sql_clear_geometry_field_metadata = 'DELETE FROM USER_SDO_GEOM_METADATA WHERE TABLE_NAME = %(table)s AND COLUMN_NAME = %(column)s'
    # public methods
    def __init__(self, *args, **kwargs):
    def geo_quote_name(self, name):
    def quote_value(self, value):
    def column_sql(self, model, field, include_default=False):
    def create_model(self, model):
    def delete_model(self, model):
    def add_field(self, model, field):
    def remove_field(self, model, field):
    def run_geometry_sql(self):
[TYPE] PostGISSchemaEditor
[DEFINITION]
class PostGISSchemaEditor(DatabaseSchemaEditor):
    # package: django
    # module: django.contrib.gis.db.backends.postgis.schema
    # source: third_party
    # fields
    geom_index_type = 'GIST'
    geom_index_ops_nd = 'GIST_GEOMETRY_OPS_ND'
    rast_index_template = 'ST_ConvexHull(%(expressions)s)'
    sql_alter_column_to_3d = 'ALTER COLUMN %(column)s TYPE %(type)s USING ST_Force3D(%(column)s)::%(type)s'
    sql_alter_column_to_2d = 'ALTER COLUMN %(column)s TYPE %(type)s USING ST_Force2D(%(column)s)::%(type)s'
    # public methods
    def geo_quote_name(self, name):
[TYPE] SpatialiteSchemaEditor
[DEFINITION]
class SpatialiteSchemaEditor(DatabaseSchemaEditor):
    # package: django
    # module: django.contrib.gis.db.backends.spatialite.schema
    # source: third_party
    # fields
    sql_add_geometry_column = 'SELECT AddGeometryColumn(%(table)s, %(column)s, %(srid)s, %(geom_type)s, %(dim)s, %(null)s)'
    sql_add_spatial_index = 'SELECT CreateSpatialIndex(%(table)s, %(column)s)'
    sql_drop_spatial_index = 'DROP TABLE idx_%(table)s_%(column)s'
    sql_recover_geometry_metadata = 'SELECT RecoverGeometryColumn(%(table)s, %(column)s, %(srid)s, %(geom_type)s, %(dim)s)'
    sql_remove_geometry_metadata = 'SELECT DiscardGeometryColumn(%(table)s, %(column)s)'
    sql_discard_geometry_columns = 'DELETE FROM %(geom_table)s WHERE f_table_name = %(table)s'
    sql_update_geometry_columns = 'UPDATE %(geom_table)s SET f_table_name = %(new_table)s WHERE f_table_name = %(old_table)s'
    geometry_tables = ['geometry_columns', 'geometry_columns_auth', 'geometry_columns_time', 'geometry_columns_statistics']
    # public methods
    def __init__(self, *args, **kwargs):
    def geo_quote_name(self, name):
    def column_sql(self, model, field, include_default=False):
    def remove_geometry_metadata(self, model, field):
    def create_model(self, model):
    def delete_model(self, model, **kwargs):
    def add_field(self, model, field):
    def remove_field(self, model, field):
    def alter_db_table(self, model, old_db_table, new_db_table):
[TYPE] DatabaseSchemaEditor
[DEFINITION]
class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):
    # package: django
    # module: django.db.backends.mysql.schema
    # source: third_party
    # fields
    sql_rename_table = 'RENAME TABLE %(old_table)s TO %(new_table)s'
    sql_alter_column_null = 'MODIFY %(column)s %(type)s NULL'
    sql_alter_column_not_null = 'MODIFY %(column)s %(type)s NOT NULL'
    sql_alter_column_type = 'MODIFY %(column)s %(type)s%(collation)s%(comment)s'
    sql_alter_column_no_default_null = 'ALTER COLUMN %(column)s SET DEFAULT NULL'
    sql_delete_unique = 'ALTER TABLE %(table)s DROP INDEX %(name)s'
    sql_create_column_inline_fk = ', ADD CONSTRAINT %(name)s FOREIGN KEY (%(column)s) REFERENCES %(to_table)s(%(to_column)s)%(on_delete_db)s'
    sql_delete_fk = 'ALTER TABLE %(table)s DROP FOREIGN KEY %(name)s'
    sql_delete_index = 'DROP INDEX %(name)s ON %(table)s'
    sql_rename_index = 'ALTER TABLE %(table)s RENAME INDEX %(old_name)s TO %(new_name)s'
    sql_create_pk = 'ALTER TABLE %(table)s ADD CONSTRAINT %(name)s PRIMARY KEY (%(columns)s)'
    sql_delete_pk = 'ALTER TABLE %(table)s DROP PRIMARY KEY'
    sql_create_index = 'CREATE INDEX %(name)s ON %(table)s (%(columns)s)%(extra)s'
    sql_alter_table_comment = 'ALTER TABLE %(table)s COMMENT = %(comment)s'
    sql_alter_column_comment = None
    # public methods
    def sql_delete_check(self):
    def quote_value(self, value):
    def skip_default(self, field):
    def skip_default_on_alter(self, field):
    def add_field(self, model, field):
    def remove_constraint(self, model, constraint):
    def remove_index(self, model, index):
```

## Độ chính xác theo nhóm kiểu dữ liệu

### Quy tắc phân loại

- Lấy kiểu ngoài cùng của annotation: `Dict[str, Any]` → `dict`, `List[Claim]` → `list`.
- **Cơ bản/typing** gồm built-in và các container/protocol phổ biến của `typing`.
- **User-defined/named** gồm các nhãn có kiểu ngoài cùng không thuộc nhóm trên. Nhóm này có thể gồm class từ standard library hoặc thư viện bên thứ ba.
- `List[Claim]` được tính vào `list` vì việc phân nhóm dựa trên kiểu ngoài cùng.

### So sánh hai nhóm

| Nhóm | Đúng | Tổng | Tỷ lệ đúng | Số nhãn chính xác khác nhau |
| --- | ---: | ---: | ---: | ---: |
| Cơ bản/typing | 1,896 | 2,230 | 85.02% | 172 |
| User-defined/named | 879 | 1,047 | 83.95% | 262 |
| **Toàn bộ** | **2,775** | **3,277** | **84.68%** | **434** |

### Chi tiết các kiểu cơ bản/typing

Các annotation có cùng kiểu ngoài cùng được gộp vào một dòng. Cột ví dụ hiển thị tối đa ba nhãn phổ biến.

| Kiểu ngoài cùng | Ví dụ nhãn | Đúng | Tổng | Tỷ lệ đúng |
| --- | --- | ---: | ---: | ---: |
| `str` | `str` | 875 | 894 | 97.87% |
| `dict` | `dict`, `Dict[str, Any]`, `Dict[str, str]` | 171 | 296 | 57.77% |
| `list` | `List[str]`, `list`, `List[int]` | 194 | 263 | 73.76% |
| `int` | `int` | 233 | 244 | 95.49% |
| `bool` | `bool` | 187 | 194 | 96.39% |
| `none` | `None` | 68 | 74 | 91.89% |
| `float` | `float` | 62 | 66 | 93.94% |
| `tuple` | `Tuple[str]`, `Tuple[int]`, `Tuple[Tuple[Model, Tensor, Tensor], bool]` | 28 | 48 | 58.33% |
| `callable` | `Callable[[], None]`, `callable`, `Callable[[], bool]` | 15 | 43 | 34.88% |
| `bytes` | `bytes` | 30 | 36 | 83.33% |
| `iterable` | `Iterable[str]`, `Iterable[int]`, `iterable` | 8 | 27 | 29.63% |
| `set` | `set`, `Set[VuforiaDatabase]`, `Set[str]` | 11 | 17 | 64.71% |
| `iterator` | `Iterator[Vehicle]`, `Iterator[int]`, `Iterator[Instance]` | 8 | 12 | 66.67% |
| `type` | `Type[Issue]`, `Type['SerializationDialect']`, `Type[List[Topic]]` | 5 | 12 | 41.67% |
| `any` | `any` | 0 | 2 | 0.00% |
| `awaitable` | `Awaitable` | 1 | 1 | 100.00% |
| `collection` | `Collection[int]` | 0 | 1 | 0.00% |

### Các kiểu user-defined/named phổ biến nhất

Toàn bộ nhóm có **879/1,047 mẫu đúng (83.95%)** trên **262 nhãn**. Bảng hiển thị 20 nhãn có nhiều mẫu nhất.

| Kiểu dữ liệu | Đúng | Tổng | Tỷ lệ đúng |
| --- | ---: | ---: | ---: |
| `Response` | 61 | 64 | 95.31% |
| `Path` | 36 | 38 | 94.74% |
| `StateHandler` | 32 | 32 | 100.00% |
| `Request` | 28 | 31 | 90.32% |
| `Vector` | 25 | 28 | 89.29% |
| `User` | 27 | 27 | 100.00% |
| `Database` | 20 | 20 | 100.00% |
| `HttpRequest` | 20 | 20 | 100.00% |
| `ConfigHandler` | 19 | 19 | 100.00% |
| `HttpResponse` | 17 | 19 | 89.47% |
| `Branch` | 17 | 18 | 94.44% |
| `Issue` | 11 | 18 | 61.11% |
| `Options` | 18 | 18 | 100.00% |
| `Finish` | 6 | 16 | 37.50% |
| `IssueGithub` | 9 | 16 | 56.25% |
| `LoginPage` | 16 | 16 | 100.00% |
| `UserProfile` | 14 | 15 | 93.33% |
| `Application` | 11 | 12 | 91.67% |
| `ScryfallDataSet` | 11 | 11 | 100.00% |
| `State` | 9 | 11 | 81.82% |
