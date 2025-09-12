TS_BUILTIN_TYPES = {
    "number", "string", "boolean", "any", "void", "null", "undefined", 
    "never", "object", "Object", "unknown", "symbol", "bigint"
}

GENERIC_TYPES = {
    "array": "Array",
    "record": "Record", 
    "promise": "Promise",
    "map": "Map",
    "set": "Set"
}
GENERIC_TYPES_SET = {"Array", "Record", "Promise", "Map", "Set"}

TYPE_CATEGORIES = {
    "BUILTIN": 0,
    "USER_DEFINED": 2, 
    "FUNCTION": 3,
    "TUPLE": 4,
    "INTERSECTION": 5
}

INVALID_TYPE_CHARS = {
    '?', '*', '-', '/', '|', '&', '^', '%', '$', '#', '@', '!', '~', '`', 
    ':', ';', ',', '.', '<', '>'
}

ANY_TYPE = None