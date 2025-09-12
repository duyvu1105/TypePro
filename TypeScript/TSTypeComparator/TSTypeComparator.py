from .TSTypeObject import TSTypeObject
from .constant_types import TS_BUILTIN_TYPES, TYPE_CATEGORIES, GENERIC_TYPES_SET


class TSTypeComparator:

    
    @staticmethod
    def is_identical(l: 'TSTypeObject', r: 'TSTypeObject') -> bool:

        if l is None or r is None:
            return False
        if getattr(l, 'type', None) == "Intersection" or getattr(r, 'type', None) == "Intersection":
            return False
        if l.type == "Object":
            return True
        if r.type == "Object" and l.type != "Object":
            return False
        if r.type == "object" and l.type != "object":
            return False
        if l.type == "object" or r.type == "object":
            primitive_types = {"number", "string", "boolean", "null", "undefined", "symbol", "bigint"}
            
            if l.type == "object" and r.type not in primitive_types:
                return True
            if r.type == "object" and l.type not in primitive_types:
                return True
            if l.type == "object" and r.type == "object":
                return True
        if l.type == "Function" and r.type == "Function":
            if not l.params and not l.return_type and (r.params or r.return_type):
                return True
            if not l.params and not l.return_type and not r.params and not r.return_type:
                return True
            if l.params and r.params and l.return_type and r.return_type:
                if len(l.params) != len(r.params):
                    return False
                for (n1, t1), (n2, t2) in zip(l.params, r.params):
                    if n1 != n2 or not TSTypeComparator.is_identical(t1, t2):
                        return False
                return TSTypeComparator.is_identical(l.return_type, r.return_type)
            return False
        if l.category == TYPE_CATEGORIES["USER_DEFINED"] and r.category == TYPE_CATEGORIES["USER_DEFINED"]:
            if l.type == r.type:
                return True
            l_main_type = l.type.split(".")[-1] if "." in l.type else l.type
            r_main_type = r.type.split(".")[-1] if "." in r.type else r.type
            if l_main_type == r_main_type:
                return True
        if l.type in GENERIC_TYPES_SET and r.type in GENERIC_TYPES_SET and l.type == r.type:
            def all_any(obj):
                return (
                    (not hasattr(obj, "element_type") or all(e.type == "any" for e in getattr(obj, "element_type", []))) and
                    (not hasattr(obj, "key_type") or all(e.type == "any" for e in getattr(obj, "key_type", []))) and
                    (not hasattr(obj, "value_type") or all(e.type == "any" for e in getattr(obj, "value_type", [])))
                )
            if all_any(l) and all_any(r):
                return True
        if l.type == r.type and l.category == TYPE_CATEGORIES["BUILTIN"] and r.category == TYPE_CATEGORIES["BUILTIN"]:
            if not l.element_type and not r.element_type and not l.key_type and not r.key_type and not l.value_type and not r.value_type:
                return True
        if (l.type == "Tuple" and r.type == "Array") or (l.type == "Array" and r.type == "Tuple"):
            if l.type == "Array":
                if not l.element_type:
                    return True
            elif r.type == "Array":
                if not r.element_type:
                    return True
            return False
        if l.type != r.type or l.category != r.category:
            return False
        if l.type in GENERIC_TYPES_SET and r.type in GENERIC_TYPES_SET:
            if len(l.element_type) != len(r.element_type):
                return False
            for a, b in zip(l.element_type, r.element_type):
                if not TSTypeComparator.is_identical(a, b):
                    return False
            if len(l.key_type) != len(r.key_type):
                return False
            for a, b in zip(l.key_type, r.key_type):
                if not TSTypeComparator.is_identical(a, b):
                    return False
            if len(l.value_type) != len(r.value_type):
                return False
            for a, b in zip(l.value_type, r.value_type):
                if not TSTypeComparator.is_identical(a, b):
                    return False
            return True
        if l.type == "Union" and r.type == "Union":
            lset = set(str(e) for e in l.element_type)
            rset = set(str(e) for e in r.element_type)
            return lset == rset
        if (l.type == "Union" and r.type == "any") or (l.type == "any" and r.type == "Union"):
            return False
        if l.element_type or r.element_type:
            if len(l.element_type) != len(r.element_type):
                return False
            if l.type == "object" and r.type == "object":
                return all(TSTypeComparator.is_identical(a[1], b[1]) for a, b in zip(l.element_type, r.element_type))
            else:
                return all(TSTypeComparator.is_identical(a, b) for a, b in zip(l.element_type, r.element_type))
        if l.type == "Function":
            if len(l.params) != len(r.params):
                return False
            for (n1, t1), (n2, t2) in zip(l.params, r.params):
                if n1 != n2 or not TSTypeComparator.is_identical(t1, t2):
                    return False
            return TSTypeComparator.is_identical(l.return_type, r.return_type)
        if l.type == "object" and r.type == "object":
            if len(l.element_type) != len(r.element_type):
                return False
            l_props = {name: typ for name, typ in l.element_type}
            r_props = {name: typ for name, typ in r.element_type}
            if set(l_props.keys()) != set(r_props.keys()):
                return False
            for name in l_props:
                if not TSTypeComparator.is_identical(l_props[name], r_props[name]):
                    return False
            return True
        return False

    @staticmethod
    def is_included(l: 'TSTypeObject', r: 'TSTypeObject') -> bool:
        if l is None or r is None:
            return False
        if getattr(l, 'type', None) == "Intersection" or getattr(r, 'type', None) == "Intersection":
            return False
        if hasattr(l, 'type') and l.type == "Object":
            return True
        if hasattr(r, 'type') and r.type == "Object" and (not hasattr(l, 'type') or l.type != "Object"):
            return False
        if hasattr(l, 'type') and l.type == "Function" and hasattr(r, 'type') and r.type == "Function":
            if not l.params and not l.return_type and (r.params or r.return_type):
                return True
            if not l.params and not l.return_type and not r.params and not r.return_type:
                return True
            if (l.params or l.return_type) and not r.params and not r.return_type:
                return False
            if l.params and r.params and l.return_type and r.return_type:
                if len(l.params) != len(r.params):
                    return False
                for (n1, t1), (n2, t2) in zip(l.params, r.params):
                    if n1 != n2:
                        return False
                    if not TSTypeComparator.is_included(t1, t2):
                        return False
                if not TSTypeComparator.is_included(l.return_type, r.return_type):
                    return False
                return True
            return False
        primitive_types = {"number", "string", "boolean", "null", "undefined", "symbol", "bigint"}
        
        if hasattr(l, 'type') and l.type == "object" and hasattr(r, 'type') and r.type not in primitive_types:
            return True
        if hasattr(r, 'type') and r.type == "object":
            if hasattr(l, 'type') and (l.type == "object" or l.type.lower() == "any"):
                return True
            else:
                return False
        if hasattr(r, 'type') and r.type and r.type.lower() == "any":
            if not (hasattr(l, 'type') and l.type and l.type.lower() == "any"):
                return False
        if hasattr(l, 'type') and l.type and l.type.lower() == "any" and (not (hasattr(r, 'type') and r.type and r.type.lower() == "any")):
            return False
        if (l.type == "Tuple" and r.type == "Array") or (l.type == "Array" and r.type == "Tuple"):
            return True
        if l.type == r.type:
            if l.type == "Union" and r.type == "Union":
                lset = set(str(e) for e in l.element_type)
                rset = set(str(e) for e in r.element_type)
                if lset & rset:
                    return True
            if l.type == "Array" and r.type == "Array":
                for a in l.element_type:
                    for b in r.element_type:
                        if b.type == "any":
                            return True
                        if TSTypeComparator.is_included(a, b):
                            return True
                return False
            if l.type in GENERIC_TYPES_SET and r.type in GENERIC_TYPES_SET:
                for a in l.element_type:
                    for b in r.element_type:
                        if b.type == "any":
                            return True
                        if TSTypeComparator.is_included(a, b):
                            return True
                for a in l.key_type:
                    for b in r.key_type:
                        if b.type == "any":
                            return True
                        if TSTypeComparator.is_included(a, b):
                            return True
                for a in l.value_type:
                    for b in r.value_type:
                        if b.type == "any":
                            return True
                        if TSTypeComparator.is_included(a, b):
                            return True
                return False
            if l.element_type or r.element_type:
                if l.type == "object" and r.type == "object":
                    for a in l.element_type:
                        for b in r.element_type:
                            if TSTypeComparator.is_included(a[1], b[1]):
                                return True
                    return False
                else:
                    for a in l.element_type:
                        for b in r.element_type:
                            if b.type == "any":
                                continue
                            if TSTypeComparator.is_included(a, b):
                                return True
                    return False
            if l.type == "Record":
                for a in l.key_type:
                    for b in r.key_type:
                        if TSTypeComparator.is_included(a, b):
                            return True
                for a in l.value_type:
                    for b in r.value_type:
                        if TSTypeComparator.is_included(a, b):
                            return True
                return False
            if l.type == "Function":
                if len(l.params) != len(r.params):
                    return False
                for (n1, t1), (n2, t2) in zip(l.params, r.params):
                    if n1 != n2:
                        return False
                    if t2.type == "any":
                        continue
                    if TSTypeComparator.is_included(t2, t1):
                        return True
                if r.return_type and r.return_type.type == "any":
                    return True
                if TSTypeComparator.is_included(l.return_type, r.return_type):
                    return True
                return False
            if l.type == "object" and r.type == "object":
                l_props = {name: typ for name, typ in l.element_type}
                r_props = {name: typ for name, typ in r.element_type}
                for name, l_typ in l_props.items():
                    if name not in r_props:
                        continue
                    if r_props[name].type == "any":
                        continue
                    if TSTypeComparator.is_included(l_typ, r_props[name]):
                        return True
                return False
            return False
        if l.type in GENERIC_TYPES_SET and r.type in GENERIC_TYPES_SET:
            for a in l.element_type:
                for b in r.element_type:
                    if b.type == "any":
                        return True
                    if TSTypeComparator.is_included(a, b):
                        return True
            for a in l.key_type:
                for b in r.key_type:
                    if b.type == "any":
                        return True
                    if TSTypeComparator.is_included(a, b):
                        return True
            for a in l.value_type:
                for b in r.value_type:
                    if b.type == "any":
                        return True
                    if TSTypeComparator.is_included(a, b):
                        return True
            return False
        if (l.type in ["Array", "Record", "Promise", "Map", "Set"] and r.type in GENERIC_TYPES_SET) or \
           (r.type in ["Array", "Record", "Promise", "Map", "Set"] and l.type in GENERIC_TYPES_SET):
            if l.type == r.type:
                return True
        if l.type == "Array" and r.type == "Array":
            for a in l.element_type:
                for b in r.element_type:
                    if b.type == "any":
                        return True
                    if TSTypeComparator.is_included(a, b):
                        return True
            return False
        if r.type.lower() == "any":
            return True
        if r.type == "Union":
            if hasattr(l, 'type') and l.type == "object":
                primitive_types = {"number", "string", "boolean", "null", "undefined", "symbol", "bigint"}
                if all(b.type not in primitive_types for b in r.element_type):
                    return True
            return any(TSTypeComparator.is_included(l, b) for b in r.element_type)
        if r.type == "Optional" and r.element_type:
            return TSTypeComparator.is_included(l, r.element_type[0])

        return False

    @staticmethod
    def is_identical_set(l_list, r_list):

        l_typeobjs = [l for l in l_list if isinstance(l, TSTypeObject)]
        r_typeobjs = [r for r in r_list if isinstance(r, TSTypeObject)]
        l_typeobjs = TSTypeObject.dedup_any_types(l_typeobjs)
        r_typeobjs = TSTypeObject.dedup_any_types(r_typeobjs)
        
        if len(l_typeobjs) == 1 and len(r_typeobjs) > 1:
            l_obj = l_typeobjs[0]
            if hasattr(l_obj, 'type') and l_obj.type == "object":
                primitive_types = {"number", "string", "boolean", "null", "undefined", "symbol", "bigint"}
                r_types = [r.type for r in r_typeobjs]
                all_non_primitive = all(t not in primitive_types for t in r_types)
                if all_non_primitive:
                    return True
        r_has_object = any(getattr(r, 'type', None) == "object" for r in r_typeobjs)
        if r_has_object:
            r_has_object_type = any(getattr(r, 'type', None) == "object" for r in r_typeobjs)
            if r_has_object_type:
                l_has_object_or_any = any(
                    (getattr(l, 'type', None) == "object") or 
                    (hasattr(l, 'type') and l.type and l.type.lower() == "any") 
                    for l in l_typeobjs
                )
                if not l_has_object_or_any:
                    return False
        
        l_has_any = any(hasattr(l, 'type') and l.type and l.type.lower() == "any" for l in l_typeobjs)
        r_has_any = any(hasattr(r, 'type') and r.type and r.type.lower() == "any" for r in r_typeobjs)
        if l_has_any:
            return True
        elif r_has_any:
            return False
        
        if len(l_typeobjs) == 1 and len(r_typeobjs) == 1:
            l_obj = l_typeobjs[0]
            r_obj = r_typeobjs[0]
            if (l_obj.type == "Tuple" and r_obj.type == "Array") or (l_obj.type == "Array" and r_obj.type == "Tuple"):
                if l_obj.type == "Array":
                    if not l_obj.element_type:
                        return True
                elif r_obj.type == "Array":
                    if not r_obj.element_type:
                        return True
                return False
            if l_obj.type == r_obj.type and l_obj.type in ["Array", "Record", "Promise", "Map", "Set"]:
                l_has_params = bool(l_obj.element_type or l_obj.key_type or l_obj.value_type)
                r_has_params = bool(r_obj.element_type or r_obj.key_type or r_obj.value_type)
                if not l_has_params and r_has_params:
                    return True
                if l_has_params and not r_has_params:
                    return False
        
        if len(l_typeobjs) == 1 and l_typeobjs[0].type in ["Array", "Record", "Promise", "Map", "Set"] and len(r_typeobjs) > 1:
            base_type = l_typeobjs[0].type
            if all(r.type == base_type for r in r_typeobjs):
                if any(r.element_type or r.key_type or r.value_type for r in r_typeobjs):
                    return True
        
        if len(l_typeobjs) == 1 and len(r_typeobjs) > 1:
            l_obj = l_typeobjs[0]
            if l_obj.type == "Function" and not l_obj.params and not l_obj.return_type:
                all_concrete_functions = True
                for r_obj in r_typeobjs:
                    if not (hasattr(r_obj, 'type') and r_obj.type == "Function" and 
                           (r_obj.params or r_obj.return_type)):
                        all_concrete_functions = False
                        break
                if all_concrete_functions:
                    return True
        
        if len(l_typeobjs) == 1 and len(r_typeobjs) == 1:
            l_obj = l_typeobjs[0]
            r_obj = r_typeobjs[0]
            if l_obj.type == "Function" and r_obj.type == "Function":
                if not l_obj.params and not l_obj.return_type and (r_obj.params or r_obj.return_type):
                    return True
                if not l_obj.params and not l_obj.return_type and not r_obj.params and not r_obj.return_type:
                    return True
                if (l_obj.params or l_obj.return_type) and not r_obj.params and not r_obj.return_type:
                    return False
                if l_obj.params and r_obj.params and l_obj.return_type and r_obj.return_type:
                    if len(l_obj.params) != len(r_obj.params):
                        return False
                    for (n1, t1), (n2, t2) in zip(l_obj.params, r_obj.params):
                        if n1 != n2 or not TSTypeComparator.is_identical(t1, t2):
                            return False
                    return TSTypeComparator.is_identical(l_obj.return_type, r_obj.return_type)
                return False
        
        lset = set(str(x) for x in l_typeobjs)
        rset = set(str(x) for x in r_typeobjs)
        if lset == rset:
            return True
        if len(l_typeobjs) == 1 and len(r_typeobjs) == 1:
            l_obj = l_typeobjs[0]
            r_obj = r_typeobjs[0]
            if l_obj.type == "object" and r_obj.type == "object":
                if l_obj.element_type and r_obj.element_type:
                    l_props = {name for name, _ in l_obj.element_type}
                    r_props = {name for name, _ in r_obj.element_type}
                    if l_props != r_props:
                        return False
                    l_prop_dict = {name: type_obj for name, type_obj in l_obj.element_type}
                    r_prop_dict = {name: type_obj for name, type_obj in r_obj.element_type}
                    for prop_name in l_props:
                        if not TSTypeComparator.is_identical(l_prop_dict[prop_name], r_prop_dict[prop_name]):
                            return False
        if len(l_typeobjs) == 1 and len(r_typeobjs) == 1:
            l_obj = l_typeobjs[0]
            r_obj = r_typeobjs[0]
            if (l_obj.type in GENERIC_TYPES_SET and r_obj.type in GENERIC_TYPES_SET and 
                l_obj.type == r_obj.type):
                def params_equivalent(l_obj, r_obj):
                    if l_obj.type in ("Array", "Set", "Promise"):
                        if len(l_obj.element_type) == 0 and len(r_obj.element_type) == 0:
                            return True
                        if len(l_obj.element_type) == 0 or len(r_obj.element_type) == 0:
                            return False
                        if len(l_obj.element_type) != len(r_obj.element_type):
                            return False
                        return all(
                            (a.type == "any" and b.type == "any") or TSTypeComparator.is_identical(a, b)
                            for a, b in zip(l_obj.element_type, r_obj.element_type)
                        )
                    elif l_obj.type == "Record":
                        l_key_any = not l_obj.key_type or all(e.type == "any" for e in l_obj.key_type)
                        r_key_any = not r_obj.key_type or all(e.type == "any" for e in r_obj.key_type)
                        l_value_any = not l_obj.value_type or all(e.type == "any" for e in l_obj.value_type)
                        r_value_any = not r_obj.value_type or all(e.type == "any" for e in r_obj.value_type)
                        return (l_key_any and r_key_any or 
                                (len(l_obj.key_type) == len(r_obj.key_type) and 
                                 all((a.type == "any" and b.type == "any") or TSTypeComparator.is_identical(a, b) for a, b in zip(l_obj.key_type, r_obj.key_type)))) and \
                               (l_value_any and r_value_any or 
                                (len(l_obj.value_type) == len(r_obj.value_type) and 
                                 all((a.type == "any" and b.type == "any") or TSTypeComparator.is_identical(a, b) for a, b in zip(l_obj.value_type, r_obj.value_type))))
                    elif l_obj.type == "Map":
                        if len(l_obj.element_type) != len(r_obj.element_type):
                            return False
                        return all(
                            (a.type == "any" and b.type == "any") or TSTypeComparator.is_identical(a, b)
                            for a, b in zip(l_obj.element_type, r_obj.element_type)
                        )
                    return False
                
                if params_equivalent(l_obj, r_obj):
                    return True
            return TSTypeComparator.is_identical(l_obj, r_obj)
        if len(l_typeobjs) > 1 or len(r_typeobjs) > 1:
            def objects_equivalent(l, r):
                if l.type == "object" and r.type == "object":
                    if l.element_type and r.element_type:
                        l_props = {name for name, _ in l.element_type}
                        r_props = {name for name, _ in r.element_type}
                        if l_props != r_props:
                            return False
                        l_prop_dict = {name: type_obj for name, type_obj in l.element_type}
                        r_prop_dict = {name: type_obj for name, type_obj in r.element_type}
                        for prop_name in l_props:
                            if not TSTypeComparator.is_identical(l_prop_dict[prop_name], r_prop_dict[prop_name]):
                                return False
                        return True
                return TSTypeComparator.is_identical(l, r)
            
            l_covered = all(
                any(objects_equivalent(l, r) for r in r_typeobjs) or 
                (hasattr(l, 'type') and l.type and l.type.lower() == "any")
                for l in l_typeobjs
            )
            r_covered = all(
                any(objects_equivalent(r, l) for l in l_typeobjs) or 
                (hasattr(r, 'type') and r.type and r.type.lower() == "any")
                for r in r_typeobjs
            )
            return l_covered and r_covered
        return False

    @staticmethod
    def exist_similar(l, listr):
        for r in listr:
            if TSTypeComparator.is_identical(l, r):
                return True
            if (hasattr(l, 'type') and hasattr(r, 'type') and 
                ((l.type == "Tuple" and r.type == "Array") or (l.type == "Array" and r.type == "Tuple"))):
                return True
            if hasattr(l, 'type') and hasattr(r, 'type') and l.type.lower() == r.type.lower():
                if l.type.lower() == "object":
                    l_is_base = not hasattr(l, 'element_type') or not l.element_type
                    r_is_base = not hasattr(r, 'element_type') or not r.element_type
                    if l_is_base and r_is_base:
                        return True
                else:
                    return True
        return False

    @staticmethod
    def exist_numbers(l, listr, exact=False):
        if not exact:
            return False
        if hasattr(l, 'type') and l.type in ["number", "float", "int"]:
            for r in listr:
                if hasattr(r, 'type') and r.type in ["number", "float", "int"]:
                    return True
        return False

    @staticmethod
    def usertype_compare(l, listr):
        for r in listr:
            if hasattr(l, 'category') and hasattr(r, 'category') and l.category == r.category == 2:
                l_main_type = l.type.split(".")[-1] if "." in l.type else l.type
                r_main_type = r.type.split(".")[-1] if "." in r.type else r.type
                if l_main_type == r_main_type:
                    return True
                if l.type == l_main_type and r.type != r_main_type and l_main_type == r_main_type:
                    return True
                if r.type == r_main_type and l.type != l_main_type and l_main_type == r_main_type:
                    return True
        return False

    @staticmethod
    def is_set_included2(llist, rlist): 
        if len(llist) == 1 and len(rlist) >= 1:
            l_obj = llist[0]
            if hasattr(l_obj, 'type') and l_obj.type == "Function":
                if not l_obj.params and not l_obj.return_type:
                    all_concrete_functions = True
                    for r_obj in rlist:
                        if not (hasattr(r_obj, 'type') and r_obj.type == "Function" and 
                               (r_obj.params or r_obj.return_type)):
                            all_concrete_functions = False
                            break
                    if all_concrete_functions:
                        return True
                if (l_obj.params or l_obj.return_type):
                    all_base_functions = True
                    for r_obj in rlist:
                        if not (hasattr(r_obj, 'type') and r_obj.type == "Function" and 
                               not r_obj.params and not r_obj.return_type):
                            all_base_functions = False
                            break
                    if all_base_functions:
                        return False
        elif len(llist) > 1 and len(rlist) == 1:
            r_obj = rlist[0]
            if hasattr(r_obj, 'type') and r_obj.type == "Function":
                if not r_obj.params and not r_obj.return_type:
                    all_concrete_functions = True
                    for l_obj in llist:
                        if not (hasattr(l_obj, 'type') and l_obj.type == "Function" and 
                               (l_obj.params or l_obj.return_type)):
                            all_concrete_functions = False
                            break
                    if all_concrete_functions:
                        return False
        elif len(llist) == 1 and len(rlist) > 1:
            l_obj = llist[0]
            if hasattr(l_obj, 'type') and l_obj.type == "Function":
                if not l_obj.params and not l_obj.return_type:
                    all_concrete_functions = True
                    for r_obj in rlist:
                        if not (hasattr(r_obj, 'type') and r_obj.type == "Function" and 
                               (r_obj.params or r_obj.return_type)):
                            all_concrete_functions = False
                            break
                    if all_concrete_functions:
                        return True
        if len(llist) == 1 and len(rlist) == 1:
            l_obj = llist[0]
            r_obj = rlist[0]
            if (hasattr(l_obj, 'type') and l_obj.type == "object" and 
                hasattr(r_obj, 'type') and r_obj.type == "Union"):
                primitive_types = {"number", "string", "boolean", "null", "undefined", "symbol", "bigint"}
                types = [b.type for b in r_obj.element_type]
                all_non_primitive = all(t not in primitive_types for t in types)
                all_primitive = all(t in primitive_types for t in types)
                if all_non_primitive:
                    return True
                if all_primitive:
                    return False
                return True
            elif hasattr(r_obj, 'type') and r_obj.type == "Union":
                primitive_types = {"number", "string", "boolean", "null", "undefined", "symbol", "bigint"}
                union_types = [b.type for b in r_obj.element_type]
                all_non_primitive = all(t not in primitive_types for t in union_types)
                all_primitive = all(t in primitive_types for t in union_types)
                has_primitive = any(t in primitive_types for t in union_types)
                has_non_primitive = any(t not in primitive_types for t in union_types)
                
                if all_non_primitive:
                    return True
                elif has_primitive and has_non_primitive:
                    return None
                elif all_primitive:
                    return False
            elif hasattr(l_obj, 'type') and l_obj.type == "Union":
                primitive_types = {"number", "string", "boolean", "null", "undefined", "symbol", "bigint"}
                union_types = [b.type for b in l_obj.element_type]
                all_non_primitive = all(t not in primitive_types for t in union_types)
                all_primitive = all(t in primitive_types for t in union_types)
                has_primitive = any(t in primitive_types for t in union_types)
                has_non_primitive = any(t not in primitive_types for t in union_types)
                
                if all_non_primitive:
                    return True
                elif has_primitive and has_non_primitive:
                    return None
                elif all_primitive:
                    return False
        elif len(llist) == 1 and len(rlist) > 1:
            l_obj = llist[0]
            if hasattr(l_obj, 'type') and l_obj.type == "object":
                primitive_types = {"number", "string", "boolean", "null", "undefined", "symbol", "bigint"}
                r_types = [r.type for r in rlist]
                all_non_primitive = all(t not in primitive_types for t in r_types)
                all_primitive = all(t in primitive_types for t in r_types)
                has_primitive = any(t in primitive_types for t in r_types)
                has_non_primitive = any(t not in primitive_types for t in r_types)
                
                if all_non_primitive:
                    return True
                elif has_primitive and has_non_primitive:
                    return True
                elif all_primitive:
                    return False
        llist = TSTypeObject.get_all_leaf_types(llist)
        rlist = TSTypeObject.get_all_leaf_types(rlist)
        llist = [l for l in llist if isinstance(l, TSTypeObject)]
        rlist = [r for r in rlist if isinstance(r, TSTypeObject)]
        
        r_has_any = any(hasattr(r, 'type') and r.type and r.type.lower() == "any" for r in rlist)
        if r_has_any:
            l_has_any = any(hasattr(l, 'type') and l.type and l.type.lower() == "any" for l in llist)
            if not l_has_any:
                return False
        
        r_has_object = any(getattr(r, 'type', None) == "object" for r in rlist)
        if r_has_object:
            r_has_object_type = any(getattr(r, 'type', None) == "object" for r in rlist)
            if r_has_object_type:
                l_has_object_or_any = any(
                    (getattr(l, 'type', None) == "object") or 
                    (hasattr(l, 'type') and l.type and l.type.lower() == "any") 
                    for l in llist
                )
                if not l_has_object_or_any:
                    return False
        
        if TSTypeComparator.is_identical_set(llist, rlist):
            return True
        
        if len(llist) == 1 and len(rlist) == 1:
            l_obj = llist[0]
            r_obj = rlist[0]
            if (l_obj.type == "Tuple" and r_obj.type == "Array") or (l_obj.type == "Array" and r_obj.type == "Tuple"):
                return True
            if l_obj.type == r_obj.type and l_obj.type in ["Array", "Record", "Promise", "Map", "Set"]:
                l_has_params = bool(l_obj.element_type or l_obj.key_type or l_obj.value_type)
                r_has_params = bool(r_obj.element_type or r_obj.key_type or r_obj.value_type)
                if l_has_params != r_has_params:
                    return True

        
        for r in rlist:
            if (TSTypeComparator.exist_similar(r, llist) or
                TSTypeComparator.exist_numbers(r, llist, exact=True) or
                TSTypeComparator.usertype_compare(r, llist)):
                continue
            else:
                included = False
                for l in llist:
                    if TSTypeComparator.is_included(l, r):
                        included = True
                        break
                if included:
                    continue
            return False
        return True
