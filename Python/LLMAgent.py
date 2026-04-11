
from openai import OpenAI, api_key
from loguru import logger
import re
from function_methods import Function_methods
from typing import List

K = 1

def replace_union(match):
    types = [t.strip() for t in match.group(0).split('|')]
    return f"typing.Union[{', '.join(types)}]"

def convert_type_annotation(type_str: str) -> str:
    pattern = r"list\s*\[\s*([\w\.]+)\s*\]"
    match = re.search(pattern, type_str)

    if match:
        original_type = match.group(1).strip()
        return re.sub(pattern, f"list[Union[Any, {original_type}]]", type_str)
    else:
        return type_str

def wrap_with_union(s: str) -> str:

    pattern = re.compile(r'dict\[\s*([^\[\]]+?)\s*\]')

    def repl(match: re.Match) -> str:
        inner = match.group(1)
        parts = []
        for p in inner.split(','):
            t = p.strip()
            if t.lower() == 'any':
                parts.append(t)
            else:
                parts.append(f'union[any, {t}]')
        return 'dict[' + ', '.join(parts) + ']'
    return pattern.sub(repl, s)

def convert_type_annotation_tuple(type_str: str) -> str:
    pattern = r"tuple\s*\[\s*([\w\.]+)\s*\]"
    match = re.search(pattern, type_str)

    if match:
        original_type = match.group(1).strip()
        return re.sub(pattern, f"tuple[Union[Any, {original_type}]]", type_str)
    else:
        return type_str


def re_build_new_ans(ans_list:List[str]):
    ans_map = {}
    for ans in ans_list:
        if ans not in ans_map.keys():
            ans_map[ans] = 1
        else:
            ans_map[ans] += 1
    sorted_dict = dict(sorted(ans_map.items(), key=lambda item: item[1], reverse=True))
    res_list = []
    for i in sorted_dict.keys():
        res_list.append([i, (float)(sorted_dict[i])/20.0])
    return res_list


class GPT_Client:
    client: OpenAI
    right_count = 0
    total_count = 0

    @classmethod
    def __init__(cls, api_key: str):
        cls.client =OpenAI(api_key=api_key, base_url="")

    @classmethod
    def generation(cls, prompt: str, other_prompt:[str]=[]) -> str:
        base_prompt = "Next, you will be provided with a piece of Python code slicing. You will infer the variable type or function return type in Python and fill in the type annotation in <mask>. Output just only the type ,which you infer, nothing else,"
        example_prompt = """
example for your output: mask: str
The code you need to make a prediction is:\n
        """
        total_prompt = base_prompt + example_prompt
        logger.debug(other_prompt)
        for i in other_prompt:
            total_prompt = total_prompt + i+"\n"

        total_prompt = total_prompt + prompt
        cls.total_prompt = total_prompt

        logger.debug(f"total prompt:{total_prompt}")
        res = cls.client.chat.completions.create(
            model="gpt-4",
            # model="deepseek-chat",
            # model = "gpt-4o-mini",
            # model="",
            messages=[
                {"role": "user",
                 "content":
                     total_prompt
                 },
            ],
            max_tokens=30,
            temperature=0.2,
            top_p=0.3,
            frequency_penalty=0,
            presence_penalty=0,
            n=K,
            # stop=["\n", "."]
        )
        if res.choices:
            logger.debug(f"res choices length:{len(res.choices)}")
            for i in range(len(res.choices)):
                logger.info(res.choices[i].message.content)

        try:
            if res.choices:
                if len(res.choices) == 0:
                    raise Exception("No response from LLM", res)
            logger.debug(res.choices[0].message.content)
            return res.choices[0].message.content
        except:
            return ""

    @classmethod
    def Generate_Type(cls, CODE: str, typePrompt: [str] = [], other_prompt = []):
        extra_prompt = "The possible types analyzed from the import information are: "
        for i in typePrompt:
            extra_prompt = extra_prompt + i +"\n"
        if len(typePrompt)>0:
            new_prompt = [extra_prompt]
            for i in other_prompt:
                new_prompt.append(i)
            other_prompt = new_prompt
        res = cls.generation(CODE, other_prompt)
        type_rec = cls.type_recommendation(res.replace("mask:", ""), CODE)
        if len(type_rec)>0:
            for i in type_rec:
                if i not in typePrompt:
                    extra_prompt = extra_prompt + i + "\n"
            new_other_prompt = [extra_prompt]
            if len(other_prompt)>0:
                for o_p in other_prompt:
                    new_other_prompt.append(o_p)
            # other_prompt.append(extra_prompt)
            res = cls.generation(CODE, new_other_prompt)
        logger.debug(f"res:{res}")
        return cls.generation_type_fix(res)

    @classmethod
    def Generate_Type_Hint2(cls, CODE: str, typePrompt: [str] = [], other_prompt = [], K = 20):
        ans = []
        for count_times in range(K):
            extra_prompt = "The possible types analyzed from the import information are: "
            for i in typePrompt:
                extra_prompt = extra_prompt + i + "\n"
            # other_prompt = [extra_prompt].extend(other_prompt) if len(typePrompt)>0 else other_prompt

            if len(typePrompt) > 0:
                new_prompt = [extra_prompt]
                for i in other_prompt:
                    new_prompt.append(i)
            else:
                new_prompt = []
                for i in other_prompt:
                    new_prompt.append(i)
            res = cls.generation(CODE, new_prompt)
            type_rec = cls.type_recommendation(res.replace("mask:", ""), CODE)
            if len(type_rec) > 0:
                # extra_prompt = "The possible types analyzed from the import information are: "
                for i in type_rec:
                    if i not in typePrompt:
                        extra_prompt = extra_prompt + i + "\n"
                new_other_prompt = [extra_prompt]
                if len(other_prompt) > 0:
                    for o_p in other_prompt:
                        new_other_prompt.append(o_p)
                # other_prompt.append(extra_prompt)
                res = cls.generation(CODE, new_other_prompt)
            logger.debug(f"res:{res}")
            ans.append(cls.generation_type_fix(res))

        return re_build_new_ans(ans)



    @classmethod
    def type_recommendation(cls, gen:str, total_prompt:str=""):
        cls.project_analyzer = Function_methods()
        res = cls.project_analyzer.calculate_similarity_for_class(gen)
        res2 = cls.project_analyzer.calculate_similarity_for_class_name(gen)
        if len(res)>0 or len(res2)>0:
            temp_data = []
            # for i in res:
            #     logger.debug(f"recommendation type:{i[0]}, similarity:{i[1]}")
            #     temp_data.append(i[0])
            for i in res2:
                logger.debug(f"recommendation type:{i}")
                if i not in total_prompt:
                    temp_data.append(i)
            return temp_data
        return []

    @classmethod
    def get_total_prompt(cls):
        return cls.total_prompt

    @classmethod
    def generation_type_fix(cls, gen_ans:str)->str:
        new_ans = gen_ans.replace("mask:","")
        fix_dict = {"string":"str",
                    "Record": "dict",
                    "number":"int",
                    "boolean":"bool",
                    "Array":"list",
                    "Union": "typing.Union"}
        for ru in fix_dict.keys():
            new_ans = new_ans.replace(ru, fix_dict[ru])
        if new_ans.startswith("{") and new_ans.endswith("}"):
            new_ans = "dict"
        elif new_ans.lower().startswith("list") or new_ans.lower().startswith("dict"):
            new_ans = new_ans.replace("<", "[").replace(">","]")
        elif new_ans.endswith("[]"):
            new_ans = re.sub(r'(\b[\w\.]+)\[\]', r'list[\1]', new_ans)
        elif "|" in new_ans:
            new_ans = re.sub(r'\b[\w\.]+(?:\s*\|\s*[\w\.]+)+\b', replace_union, new_ans)
        new_ans = new_ans.strip()
        if new_ans.startswith("list["):
            new_ans = convert_type_annotation(new_ans)
        if new_ans.startswith("List["):
            new_ans = convert_type_annotation(new_ans.replace("List","list"))
        if new_ans.startswith("dict["):
            new_ans = wrap_with_union(new_ans)
        if new_ans.startswith("Dict["):
            new_ans = wrap_with_union(new_ans.replace("Dict", "dict"))
        if new_ans.startswith("tuple["):
            new_ans = convert_type_annotation_tuple(new_ans)
        return new_ans

if __name__ == "__main__":
    pass