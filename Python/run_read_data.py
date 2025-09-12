import os
from loguru import logger
import time
import sys

args = sys.argv[1:]
if len(args) == 0:
    logger.error("")
    sys.exit()
target_dir = args[0]
logger.warning("")
exit_code = os.system("python readFunctionDefined.py {}".format(target_dir))

if exit_code == 0:
    logger.debug("")
else:
    logger.debug(f"{exit_code}")

logger.warning("")

exit_code = os.system("python readClassDefined.py {}".format(target_dir))

if exit_code == 0:
    logger.debug("")
else:
    logger.debug(f"{exit_code}")


logger.warning("")
exit_code = os.system("python readFunctionUseData.py {}".format(target_dir))

if exit_code == 0:
    logger.debug("")
else:
    logger.debug(f"{exit_code}")