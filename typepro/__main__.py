"""One lazy entry point for CPU and GPU stages."""
import argparse
import importlib
import sys

from typepro.runtime import run_main

COMMANDS = {
    'process-data': 'typepro.data.prepare',
    'preprocess': 'typepro.data.preprocess',
    'merge': 'typepro.data.merge',
    'verify': 'typepro.data.verify',
    'finetune': 'typepro.training.generative',
    'finetune-ranker': 'typepro.training.contrastive',
    'infer': 'typepro.inference.generative',
    'infer-ranker': 'typepro.inference.contrastive',
    'infer-api': 'typepro.inference.deepseek',
    'publish': 'typepro.publishing.final',
    'publish-shard': 'typepro.publishing.shard',
}


def main():
    parser = argparse.ArgumentParser(description='TypePro: process data, finetune, infer and publish')
    parser.add_argument('command', choices=COMMANDS)
    parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Arguments for the selected stage; use COMMAND --help')
    args = parser.parse_args()
    sys.argv = [args.command, *args.arguments]
    run_main(lambda: importlib.import_module(COMMANDS[args.command]).main(), args.command)


if __name__ == '__main__':
    main()
