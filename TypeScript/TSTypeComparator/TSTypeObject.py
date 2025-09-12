import re
from typing import List, Tuple
from .constant_types import TS_BUILTIN_TYPES, TYPE_CATEGORIES, GENERIC_TYPES_SET, INVALID_TYPE_CHARS


class TSTypeParser:
    
    
    @staticmethod
    def _is_outer_paren(type_str: str) -> bool:
        """Check if outer parentheses are properly paired"""
        if not (type_str.startswith('(') and type_str.endswith(')')):
            return False
        depth = 0
        for i, c in enumerate(type_str):
            if c == '(': 
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0 and i != len(type_str) - 1:
                    return False
        return depth == 0

    @staticmethod
    def _strip_outer_parens(type_str: str) -> str:
        """Strip outer parentheses"""
        while (
            type_str.startswith('(') and type_str.endswith(')')
            and TSTypeParser._is_outer_paren(type_str)
        ):
            type_str = type_str[1:-1].strip()
            if not type_str:
                return ""
        return type_str

    @staticmethod
    def _split_type(type_str: str, sep: str) -> List[str]:
        """Split type with bracket nesting support, including object types {}"""
        type_str = TSTypeParser._strip_outer_parens(type_str)
        parts = []
        depth = 0
        last = 0
        for i, c in enumerate(type_str):
            if c in '<[{(':
                depth += 1
            elif c in '>]})':
                depth -= 1
            elif c == sep and depth == 0:
                part = type_str[last:i].strip()
                if part:
                    parts.append(part)
                last = i + 1
        part = type_str[last:].strip()
        if part:
            parts.append(part)
        return parts

    @staticmethod
    def _split_generic(inner: str) -> List[str]:
        """Split generic parameters with nesting support, including object types"""
        parts = []
        depth = 0
        last = 0
        for i, c in enumerate(inner):
            if c in '<[{(':
                depth += 1
            elif c in '>]})':
                depth -= 1
            elif c == ',' and depth == 0:
                part = inner[last:i].strip()
                if part:
                    parts.append(part)
                last = i + 1
        part = inner[last:].strip()
        if part:
            parts.append(part)
        return parts

    @staticmethod
    def _split_params(params_str: str) -> List[str]:
        """Split function parameters with nesting support"""
        parts = []
        depth = 0
        last = 0
        for i, c in enumerate(params_str):
            if c == '<' or c == '[' or c == '(':
                depth += 1
            elif c == '>' or c == ']' or c == ')':
                depth -= 1
            elif c == ',' and depth == 0:
                part = params_str[last:i].strip()
                if part:
                    parts.append(part)
                last = i + 1
        part = params_str[last:].strip()
        if part:
            parts.append(part)
        return [p for p in parts if p]


class TSTypeObject:
    
    def __init__(self, type_name: str, category: int, *,
                 element_type=None, key_type=None, value_type=None, 
                 params=None, return_type=None):
        self.type = type_name
        self.category = category
        self.element_type = element_type or []
        self.key_type = key_type or []
        self.value_type = value_type or []
        self.params = params or []
        self.return_type = return_type

    def __str__(self):
        if self.type == "Array" and self.element_type:
            return f"Array<{','.join(str(e) for e in self.element_type)}>"
        if self.type == "Record" and self.key_type and self.value_type:
            return f"Record<{str(self.key_type[0])},{str(self.value_type[0])}>"
        if self.type == "Map" and self.element_type and len(self.element_type) == 2:
            return f"Map<{str(self.element_type[0])},{str(self.element_type[1])}>"
        if self.type == "Set" and self.element_type:
            return f"Set<{str(self.element_type[0])}>"
        if self.type == "Promise" and self.element_type:
            return f"Promise<{str(self.element_type[0])}>"
        if self.type == "Union" and self.element_type:
            return " | ".join(str(e) for e in self.element_type)
        if self.type == "Intersection" and self.element_type:
            return " & ".join(str(e) for e in self.element_type)
        if self.type == "Optional" and self.element_type:
            return f"{str(self.element_type[0])}?"
        if self.type == "Tuple" and self.element_type:
            return "[" + ", ".join(str(e) for e in self.element_type) + "]"
        if self.type == "Function":
            if not self.params and not self.return_type:
                return "Function"
            params = ", ".join(f"{n}: {t}" for n, t in self.params)
            return f"({params}) => {self.return_type}"
        if self.type == "object" and self.element_type:
            props = []
            for name, typ in self.element_type:
                props.append(f"{name}: {str(typ)}")
            return "{" + ", ".join(props) + "}"
        return self.type

    @staticmethod
    def _check_union_contains_any(union_elements):
        """Check if the union type elements contain any type"""
        for element in union_elements:
            if hasattr(element, 'type') and element.type == 'any':
                return True
        return False

    @staticmethod
    def _create_union_or_any(union_elements):
        if TSTypeObject._check_union_contains_any(union_elements):
            return TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])
        else:
            return TSTypeObject("Union", TYPE_CATEGORIES["BUILTIN"], element_type=union_elements)

    @staticmethod
    def dedup_any_types(type_objs):
        any_objs = [obj for obj in type_objs if getattr(obj, 'type', None) == 'any']
        if any_objs:
            return any_objs
        from collections import defaultdict
        result = []
        grouped = defaultdict(list)
        for obj in type_objs:
            if hasattr(obj, 'type') and obj.type in ("Array", "Set", "Promise"):
                grouped[obj.type].append(obj)
            elif hasattr(obj, 'type') and obj.type == "Record":
                grouped["Record"].append(obj)
            elif hasattr(obj, 'type') and obj.type == "Map":
                grouped["Map"].append(obj)
            else:
                result.append(obj)
        for typ, objs in grouped.items():
            if typ in ("Array", "Set", "Promise"):
                result.extend(objs)
            elif typ == "Record":
                result.extend(objs)
            elif typ == "Map":
                result.extend(objs)
        return result

    @staticmethod
    def str2obj(type_str: str) -> List['TSTypeObject']:
        type_str = type_str.strip()
        if not type_str or type_str in INVALID_TYPE_CHARS:
            return []
        type_str = TSTypeParser._strip_outer_parens(type_str)
        if not type_str:
            return []
        func_match = re.match(r'^\((.*?)\)\s*=>\s*(.+)$', type_str)
        if func_match:
            return TSTypeObject.dedup_any_types(TSTypeObject._parse_function_type(func_match.groups()))
        if type_str.startswith('[') and type_str.endswith(']'):
            return TSTypeObject.dedup_any_types(TSTypeObject._parse_tuple_type(type_str))
        if '|' in type_str:
            parts = TSTypeParser._split_type(type_str, '|')
            if len(parts) == 1 and parts[0] == type_str:
                pass
            else:
                expanded_parts = []
                for p in parts:
                    p = p.strip()
                    if not p:
                        continue
                    if '&' in p:
                        cross_objs = TSTypeObject.str2obj(p)
                        if cross_objs:
                            for obj in cross_objs:
                                if obj.type == "object" and hasattr(obj, 'element_type') and obj.element_type:
                                    cross_parts = TSTypeParser._split_type(p, '&')
                                    for cross_part in cross_parts:
                                        cross_part = cross_part.strip()
                                        if cross_part.startswith('(') and cross_part.endswith(')'):
                                            cross_part = cross_part[1:-1]
                                        cross_obj = TSTypeObject.str2obj(cross_part)
                                        if cross_obj:
                                            expanded_parts.extend(cross_obj)
                                    expanded_parts.append(obj)
                                    break
                            else:
                                expanded_parts.extend(cross_objs)
                        else:
                            expanded_parts.append(p)
                    else:
                        expanded_parts.append(p)
                
                all_object_types = []
                other_types = []
                
                for p in expanded_parts:
                    if isinstance(p, str):
                        objs = TSTypeObject.str2obj(p)
                    else:
                        objs = [p]
                    
                    if objs:
                        for obj in objs:
                            if obj.type == "object" and hasattr(obj, 'element_type') and obj.element_type:
                                all_object_types.append(obj)
                            else:
                                other_types.append(obj)
                
                result = []
                if all_object_types:
                    for obj in all_object_types:
                        result.append(obj)
                    
                    for i in range(len(all_object_types)):
                        for j in range(i + 1, len(all_object_types)):
                            obj1 = all_object_types[i]
                            obj2 = all_object_types[j]
                            merged_properties = []
                            if hasattr(obj1, 'element_type') and obj1.element_type:
                                merged_properties.extend(obj1.element_type)
                            if hasattr(obj2, 'element_type') and obj2.element_type:
                                merged_properties.extend(obj2.element_type)
                            if merged_properties:
                                merged_obj = TSTypeObject("object", TYPE_CATEGORIES["BUILTIN"], element_type=merged_properties)
                                result.append(merged_obj)
                
                result.extend(other_types)
                
                return TSTypeObject.dedup_any_types(result)
        m = re.match(r"^(\w+)<(.+)>$", type_str)
        if m:
            gen_type, inner = m.groups()
            gen_type = gen_type[0].upper() + gen_type[1:]
            return TSTypeObject.dedup_any_types(TSTypeObject._parse_generic_type((gen_type, inner)))
        if '&' in type_str:
            return []
        if type_str.endswith('?'):
            base = type_str[:-1]
            if base in TS_BUILTIN_TYPES:
                return [TSTypeObject(type_str, TYPE_CATEGORIES["USER_DEFINED"])]
            return TSTypeObject.dedup_any_types(TSTypeObject._parse_optional_type(type_str))
        if type_str.endswith('[]'):
            return TSTypeObject.dedup_any_types(TSTypeObject._parse_array_type(type_str))
        if type_str.startswith('{') and type_str.endswith('}'):
            return TSTypeObject.dedup_any_types(TSTypeObject._parse_object_type(type_str))
        if '.' in type_str:
            return TSTypeObject.dedup_any_types(TSTypeObject._parse_dotted_type(type_str))
        return TSTypeObject.dedup_any_types(TSTypeObject._parse_basic_type(type_str))

    @staticmethod
    def _parse_function_type(groups: Tuple[str, str]) -> List['TSTypeObject']:
        import itertools
        params_str, ret_str = groups
        param_name_lists = []
        param_type_lists = []
        if params_str.strip():
            for p in TSTypeParser._split_params(params_str):
                if ':' in p:
                    name, typ = p.split(':', 1)
                    typ_objs = TSTypeObject.str2obj(typ.strip())
                    if typ_objs:
                        if len(typ_objs) == 1 and getattr(typ_objs[0], 'type', None) == "Union":
                            param_type_lists.append(typ_objs[0].element_type)
                        else:
                            param_type_lists.append(typ_objs)
                        param_name_lists.append(name.strip())
                    else:
                        param_type_lists.append([TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])] )
                        param_name_lists.append(name.strip())
                else:
                    param_type_lists.append([TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])] )
                    param_name_lists.append(p.strip())
        return_type_objs = TSTypeObject.str2obj(ret_str.strip())
        if not return_type_objs:
            return []
        return_type = return_type_objs[0]
        result = []
        for prod in itertools.product(*param_type_lists) if param_type_lists else [()]:
            params = list(zip(param_name_lists, prod)) if param_name_lists else []
            result.append(TSTypeObject("Function", TYPE_CATEGORIES["FUNCTION"], params=params, return_type=return_type))
        return result

    @staticmethod
    def _parse_tuple_type(type_str: str) -> List['TSTypeObject']:
        inner = type_str[1:-1]
        elements = TSTypeParser._split_generic(inner)
        result = []
        for e in elements:
            objs = TSTypeObject.str2obj(e)
            if objs:
                result.append(objs[0])
        return [TSTypeObject("Tuple", TYPE_CATEGORIES["TUPLE"], element_type=result)]

    @staticmethod
    def _parse_union_type(type_str: str) -> List['TSTypeObject']:
        parts = TSTypeParser._split_type(type_str, '|')
        if len(parts) > 1:
            all_combinations = []
            all_object_types = []
            other_types = []
            
            for p in parts:
                objs = TSTypeObject.str2obj(p)
                if objs:
                    obj = objs[0]
                    if obj.type == "Intersection":
                        intersection_parts = obj.element_type
                        for part in intersection_parts:
                            if part.type == "object" and hasattr(part, 'element_type') and part.element_type:
                                all_object_types.append(part)
                            else:
                                other_types.append(part)
                    elif obj.type == "object" and hasattr(obj, 'element_type') and obj.element_type:
                        all_object_types.append(obj)
                    else:
                        other_types.append(obj)
            

            if all_object_types:

                for obj in all_object_types:
                    all_combinations.append(obj)
                
                for i in range(len(all_object_types)):
                    for j in range(i + 1, len(all_object_types)):
                        obj1 = all_object_types[i]
                        obj2 = all_object_types[j]
                        merged_properties = []
                        if hasattr(obj1, 'element_type') and obj1.element_type:
                            merged_properties.extend(obj1.element_type)
                        if hasattr(obj2, 'element_type') and obj2.element_type:
                            merged_properties.extend(obj2.element_type)
                        if merged_properties:
                            merged_obj = TSTypeObject("object", TYPE_CATEGORIES["BUILTIN"], element_type=merged_properties)
                            all_combinations.append(merged_obj)
                
                if len(all_object_types) > 2:
                    for i in range(len(all_object_types)):
                        for j in range(i + 1, len(all_object_types)):
                            for k in range(j + 1, len(all_object_types)):
                                obj1 = all_object_types[i]
                                obj2 = all_object_types[j]
                                obj3 = all_object_types[k]
                                merged_properties = []
                                if hasattr(obj1, 'element_type') and obj1.element_type:
                                    merged_properties.extend(obj1.element_type)
                                if hasattr(obj2, 'element_type') and obj2.element_type:
                                    merged_properties.extend(obj2.element_type)
                                if hasattr(obj3, 'element_type') and obj3.element_type:
                                    merged_properties.extend(obj3.element_type)
                                if merged_properties:
                                    merged_obj = TSTypeObject("object", TYPE_CATEGORIES["BUILTIN"], element_type=merged_properties)
                                    all_combinations.append(merged_obj)
            
            all_combinations.extend(other_types)
            
            unique_combinations = []
            seen = set()
            for obj in all_combinations:
                obj_str = str(obj)
                if obj_str not in seen:
                    seen.add(obj_str)
                    unique_combinations.append(obj)
            
            return unique_combinations
        return []

    @staticmethod
    def _parse_intersection_type(type_str: str) -> List['TSTypeObject']:
        return []

    @staticmethod
    def _parse_optional_type(type_str: str) -> List['TSTypeObject']:
        base = type_str[:-1]
        base_objs = TSTypeObject.str2obj(base)
        if not base_objs:
            return []
        return [TSTypeObject("Optional", TYPE_CATEGORIES["BUILTIN"], element_type=[base_objs[0]])]

    @staticmethod
    def _parse_array_type(type_str: str) -> List['TSTypeObject']:
        base = type_str[:-2]
        if '|' in base and base.startswith('(') and base.endswith(')'):
            inner_content = base[1:-1].strip()
            if '|' in inner_content:
                union_parts = TSTypeParser._split_type(inner_content, '|')
                union_elements = []
                for part in union_parts:
                    part = part.strip()
                    if part:
                        part_objs = TSTypeObject.str2obj(part)
                        if part_objs:
                            union_elements.append(part_objs[0])
                
                if union_elements:
                    union_type = TSTypeObject._create_union_or_any(union_elements)
                    return [TSTypeObject("Array", TYPE_CATEGORIES["BUILTIN"], element_type=[union_type])]
        
        base_objs = TSTypeObject.str2obj(base)
        if not base_objs:
            return []
        return [TSTypeObject("Array", TYPE_CATEGORIES["BUILTIN"], element_type=[b]) for b in base_objs]

    @staticmethod
    def _parse_object_type(type_str: str) -> List['TSTypeObject']:
        inner = type_str[1:-1].strip()
        if not inner:
            return [TSTypeObject("object", TYPE_CATEGORIES["BUILTIN"])]
        
        inner = inner.replace(';', ',')
        
        properties = []
        depth = 0
        last = 0
        for i, c in enumerate(inner):
            if c == '{' or c == '<' or c == '[' or c == '(': 
                depth += 1
            elif c == '}' or c == '>' or c == ']' or c == ')':
                depth -= 1
            elif c == ',' and depth == 0:
                prop = inner[last:i].strip()
                if prop:
                    properties.append(prop)
                last = i + 1
        prop = inner[last:].strip()
        if prop:
            properties.append(prop)
        
        prop_name_list = []
        prop_typeobj_lists = []
        for prop in properties:
            if ':' in prop:
                name, typ = prop.split(':', 1)
                name = name.strip()
                typ = typ.strip()
                is_optional = False
                if name.endswith('?'):
                    is_optional = True
                    name = name[:-1].strip()
                typ_objs = TSTypeObject.str2obj(typ)
                if not typ_objs:
                    typ_objs = [TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])]
                if is_optional:
                    prop_typeobj_lists.append([(name, t) for t in typ_objs] + [None])
                else:
                    prop_typeobj_lists.append([(name, t) for t in typ_objs])
                prop_name_list.append(name)
        
        from itertools import product
        result = []
        for prod in product(*prop_typeobj_lists):
            obj_properties = [p for p in prod if p is not None]
            if len(set(n for n, _ in obj_properties)) != len(obj_properties):
                continue
            result.append(TSTypeObject("object", TYPE_CATEGORIES["BUILTIN"], element_type=obj_properties))
        return result

    @staticmethod
    def _parse_generic_type(groups: Tuple[str, str]) -> List['TSTypeObject']:
        gen_type, inner = groups
        gen_type_lower = gen_type.lower()
        params = [p for p in TSTypeParser._split_generic(inner) if p.strip()]
        
        if gen_type_lower == "array":
            return TSTypeObject._parse_array_generic(params)
        elif gen_type_lower == "record":
            return TSTypeObject._parse_record_generic(params)
        elif gen_type_lower == "promise":
            return TSTypeObject._parse_promise_generic(params)
        elif gen_type_lower == "map":
            return TSTypeObject._parse_map_generic(params)
        elif gen_type_lower == "set":
            return TSTypeObject._parse_set_generic(params)
        else:
            return TSTypeObject._parse_other_generic(gen_type, params)

    @staticmethod
    def _parse_array_generic(params: List[str]) -> List['TSTypeObject']:
        if len(params) != 1:
            return [TSTypeObject("Array", TYPE_CATEGORIES["BUILTIN"], element_type=[TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])])]
        
        param = params[0].strip()
        if '|' in param:
            union_parts = TSTypeParser._split_type(param, '|')
            union_elements = []
            for part in union_parts:
                part = part.strip()
                if part:
                    part_objs = TSTypeObject.str2obj(part)
                    if part_objs:
                        union_elements.append(part_objs[0])
            
            if union_elements:
                union_type = TSTypeObject._create_union_or_any(union_elements)
                return [TSTypeObject("Array", TYPE_CATEGORIES["BUILTIN"], element_type=[union_type])]
        
        base_objs = TSTypeObject.str2obj(params[0])
        if not base_objs:
            return []
        return [TSTypeObject("Array", TYPE_CATEGORIES["BUILTIN"], element_type=[b]) for b in base_objs]

    @staticmethod
    def _parse_record_generic(params: List[str]) -> List['TSTypeObject']:
        if len(params) != 2:
            return [TSTypeObject("Record", TYPE_CATEGORIES["BUILTIN"], 
                                key_type=[TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])], 
                                value_type=[TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])])]
        
        key_param = params[0].strip()
        if '|' in key_param:
            key_union_parts = TSTypeParser._split_type(key_param, '|')
            key_union_elements = []
            for part in key_union_parts:
                part = part.strip()
                if part:
                    part_objs = TSTypeObject.str2obj(part)
                    if part_objs:
                        key_union_elements.append(part_objs[0])
            key_type = [TSTypeObject._create_union_or_any(key_union_elements)] if key_union_elements else []
        else:
            key_objs = TSTypeObject.str2obj(params[0])
            key_type = [key_objs[0]] if key_objs else []
        
        value_param = params[1].strip()
        if '|' in value_param:
            value_union_parts = TSTypeParser._split_type(value_param, '|')
            value_union_elements = []
            for part in value_union_parts:
                part = part.strip()
                if part:
                    part_objs = TSTypeObject.str2obj(part)
                    if part_objs:
                        value_union_elements.append(part_objs[0])
            value_type = [TSTypeObject._create_union_or_any(value_union_elements)] if value_union_elements else []
        else:
            value_objs = TSTypeObject.str2obj(params[1])
            value_type = [value_objs[0]] if value_objs else []
        
        if not key_type or not value_type:
            return []
        
        return [TSTypeObject("Record", TYPE_CATEGORIES["BUILTIN"], key_type=key_type, value_type=value_type)]

    @staticmethod
    def _parse_promise_generic(params: List[str]) -> List['TSTypeObject']:
        if len(params) != 1:
            return [TSTypeObject("Promise", TYPE_CATEGORIES["BUILTIN"], element_type=[TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])])]
        
        param = params[0].strip()
        if '|' in param:
            union_parts = TSTypeParser._split_type(param, '|')
            union_elements = []
            for part in union_parts:
                part = part.strip()
                if part:
                    part_objs = TSTypeObject.str2obj(part)
                    if part_objs:
                        union_elements.append(part_objs[0])
            
            if union_elements:
                union_type = TSTypeObject._create_union_or_any(union_elements)
                return [TSTypeObject("Promise", TYPE_CATEGORIES["BUILTIN"], element_type=[union_type])]
        
        base_objs = TSTypeObject.str2obj(params[0])
        if not base_objs:
            return []
        return [TSTypeObject("Promise", TYPE_CATEGORIES["BUILTIN"], element_type=[b]) for b in base_objs]

    @staticmethod
    def _parse_map_generic(params: List[str]) -> List['TSTypeObject']:
        if len(params) != 2:
            return [TSTypeObject("Map", TYPE_CATEGORIES["BUILTIN"], 
                                element_type=[TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"]), 
                                            TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])])]
        
        key_param = params[0].strip()
        if '|' in key_param:
            key_union_parts = TSTypeParser._split_type(key_param, '|')
            key_union_elements = []
            for part in key_union_parts:
                part = part.strip()
                if part:
                    part_objs = TSTypeObject.str2obj(part)
                    if part_objs:
                        key_union_elements.append(part_objs[0])
            key_type = TSTypeObject._create_union_or_any(key_union_elements) if key_union_elements else None
        else:
            key_objs = TSTypeObject.str2obj(params[0])
            key_type = key_objs[0] if key_objs else None
        
        value_param = params[1].strip()
        if '|' in value_param:
            value_union_parts = TSTypeParser._split_type(value_param, '|')
            value_union_elements = []
            for part in value_union_parts:
                part = part.strip()
                if part:
                    part_objs = TSTypeObject.str2obj(part)
                    if part_objs:
                        value_union_elements.append(part_objs[0])
            value_type = TSTypeObject._create_union_or_any(value_union_elements) if value_union_elements else None
        else:
            value_objs = TSTypeObject.str2obj(params[1])
            value_type = value_objs[0] if value_objs else None
        
        if not key_type or not value_type:
            return []
        
        return [TSTypeObject("Map", TYPE_CATEGORIES["BUILTIN"], element_type=[key_type, value_type])]

    @staticmethod
    def _parse_set_generic(params: List[str]) -> List['TSTypeObject']:
        if len(params) != 1:
            return [TSTypeObject("Set", TYPE_CATEGORIES["BUILTIN"], element_type=[TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])])]
        
        param = params[0].strip()
        if '|' in param:
            union_parts = TSTypeParser._split_type(param, '|')
            union_elements = []
            for part in union_parts:
                part = part.strip()
                if part:
                    part_objs = TSTypeObject.str2obj(part)
                    if part_objs:
                        union_elements.append(part_objs[0])
            
            if union_elements:
                union_type = TSTypeObject._create_union_or_any(union_elements)
                return [TSTypeObject("Set", TYPE_CATEGORIES["BUILTIN"], element_type=[union_type])]
        
        base_objs = TSTypeObject.str2obj(params[0])
        if not base_objs:
            return []
        return [TSTypeObject("Set", TYPE_CATEGORIES["BUILTIN"], element_type=[b]) for b in base_objs]

    @staticmethod
    def _parse_other_generic(gen_type: str, params: List[str]) -> List['TSTypeObject']:
        if len(params) == 0:
            return [TSTypeObject(gen_type, TYPE_CATEGORIES["BUILTIN"], element_type=[TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"])])]
        
        element_types = []
        for param in params:
            param = param.strip()
            if '|' in param:
                union_parts = TSTypeParser._split_type(param, '|')
                union_elements = []
                for part in union_parts:
                    part = part.strip()
                    if part:
                        part_objs = TSTypeObject.str2obj(part)
                        if part_objs:
                            union_elements.append(part_objs[0])
                
                if union_elements:
                    union_type = TSTypeObject._create_union_or_any(union_elements)
                    element_types.append(union_type)
                else:
                    element_types.append(TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"]))
            else:
                param_objs = TSTypeObject.str2obj(param)
                element_types.append(param_objs[0] if param_objs else TSTypeObject("any", TYPE_CATEGORIES["BUILTIN"]))
        
        return [TSTypeObject(gen_type, TYPE_CATEGORIES["BUILTIN"], element_type=element_types)]

    @staticmethod
    def _parse_dotted_type(type_str: str) -> List['TSTypeObject']:
        if '<' in type_str:
            generic_start = type_str.find('<')
            base_type = type_str[:generic_start].strip()
            generic_part = type_str[generic_start:].strip()
            
            if '.' in base_type:
                type_name = base_type.split('.')[-1]
                return [TSTypeObject(base_type, TYPE_CATEGORIES["USER_DEFINED"])]
            else:
                return TSTypeObject._parse_generic_type((base_type, generic_part[1:-1]))
        else:
            return [TSTypeObject(type_str, TYPE_CATEGORIES["USER_DEFINED"])]

    @staticmethod
    def _parse_basic_type(type_str: str) -> List['TSTypeObject']:
        if type_str.lower() == "array":
            return [TSTypeObject("Array", TYPE_CATEGORIES["BUILTIN"])]
        if type_str.lower() == "record":
            return [TSTypeObject("Record", TYPE_CATEGORIES["BUILTIN"])]
        if type_str.lower() == "promise":
            return [TSTypeObject("Promise", TYPE_CATEGORIES["BUILTIN"])]
        if type_str.lower() == "map":
            return [TSTypeObject("Map", TYPE_CATEGORIES["BUILTIN"])]
        if type_str.lower() == "set":
            return [TSTypeObject("Set", TYPE_CATEGORIES["BUILTIN"])]
        if type_str.lower() == "function":
            return [TSTypeObject("Function", TYPE_CATEGORIES["FUNCTION"])]
            
        if type_str in TS_BUILTIN_TYPES:
            return [TSTypeObject(type_str, TYPE_CATEGORIES["BUILTIN"])]
            
        return [TSTypeObject(type_str, TYPE_CATEGORIES["USER_DEFINED"])]

    @staticmethod
    def safe_obj(type_str: str) -> 'TSTypeObject':
        objs = TSTypeObject.str2obj(type_str)
        return objs[0] if objs else None

    @staticmethod
    def get_all_leaf_types(type_input) -> list:
        def _collect_leaves(obj):
            if obj is None:
                return []
            if hasattr(obj, 'type') and obj.type in ("Union", "Intersection"):
                leaves = []
                for e in getattr(obj, 'element_type', []):
                    leaves.extend(_collect_leaves(e))
                return leaves
            return [obj]
        
        leaves = []
        if isinstance(type_input, list):
            for obj in type_input:
                leaves.extend(_collect_leaves(obj))
        else:
            objs = TSTypeObject.str2obj(type_input)
            for obj in objs:
                leaves.extend(_collect_leaves(obj))
        return TSTypeObject.dedup_any_types(leaves)

