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