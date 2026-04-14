# TypePro

This is the tool released in the paper *TypePro: Boosting LLM-Based Type Inference via Inter-Procedural Slicing*

## Requirements
- Python:
    Python >= 3.9
    Required packages: hityper, Openai, textdistance, loguru

- TypeScript:
    Node.js >= 16.0.0
    Required packages: ts-morph, stringSimilarity, ts-node

## Usage
1. Download the processed datasets based on TypeGen from the released [resources](https://) for python and Manytypes4Typescript [resources](https://huggingface.co/datasets/kevinjesse/ManyTypes4TypeScript).

2. slicing
- TypeScript: 
    It requires TSSlicer from Slicing/SlicingClass.ts and calls the `Slicing` method. Slicing requires the contents of a `CodeData` data structure. The `node` and `dataType` fields in this data structure must be correct; the rest of the content can be empty. An example is as follows:

```ts
    const path = "./yourFilePath.ts"
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(path);
    let codeSlicer = new TSSlicer(path)
    let VarNodes = sourceFile.getVariableDeclarations().filter(node => node.getName() == "yourVarName")
    let test = { node: VarNodes, type: "", filePath: path, dataType: DataType.Var }
    let res = codeSlicer.Slicing(test)
```

- Python
    It requires the Slicer class from slicing_code_class and uses the `slicing_var`, `slicing_par`, and `slicing_ret` methods for var, params, and ret, respectively. The required contents are the target node, the root ast node, and the target file. Example:

```python
    var_slicer = Slicer(FILE_PATH)
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        source = f.read()
    target_var = "Your_Var"
    data, root = var_slicer.find_var_node(FILE_PATH, target_var)
    ans = var_slicer.slicing_var(data, root, FILE_PATH)
    other_prompt = var_slicer.get_other_prompt()
```

- It requires building inter-procedural information and running the script `Scripts/run.py` (run_read_data.py for Python) before slicing.

```bash
    python Scripts/run.py your_project_path
```


3. Prompt and Generation
    The slicing process includes the first type recommendation. You need to replace the `base_url` and `api_key` in `LLMAgent` with your correct values, create an LLMAgent class, and call the `GenerationType` method.

## Run

When you need to run the program on the dataset,You need to first download the repos of the dataset to the repos folder in the root directory, and then you can use the correct `dataset_path` in `Test.ts`, download the relevant repositories to the correct location, and specify the repositories root directory in the code.

### python

- To run the Python experiment, please execute `run.py`.

Before running, please prepare the dataset and `api_key`.

1. Replace `api_key` and `dataset_path` in `run.py`. The format of `dataset` is as follows:

```json
    [{
        "cat": "builtins",
        "file": "repos/Alissonrgs/honeydock/src/email.py",
        "generic": false,
        "gttype": "int",
        "loc": "send_email_alert@global",
        "name": "option",
        "origttype": "builtins.int",
        "processed_gttype": "int",
        "scope": "arg",
        "type_depth": 0
    },
    ...
    ]
```

2. Create a `repos` directory under your Python directory and place the corresponding `project` folder for your dataset in this directory.

### typescript
 - If you don't want to run the entire dataset, you can try this.
```bash
ts-node run.ts InputProjectPath Out.json
```
- This will run and output the files in the folder corresponding to InputProjectPath to out.json.
- If you encounter errors at runtime, you can try modifying configurations in `tsconfig.json` such as `module` and `forceConsistentCasingInFileNames`.

## Evaluation

All results are saved in `RQ Results`. Run `compute_metrics_py.py` to obtain Python evaluation results, and `compute_metrics_ts.py` to obtain TypeScript evaluation results.

```bash
    python compute_metrics_py.py
    python compute_metrics_ts.py
```
   
## RQ Rsults

We store all experimental results in `RQ Results`.