import os
from loguru import logger
import time
import sys
args = sys.argv[1:]
if len(args) == 0:
    logger.error("Please add the target project directory")
    sys.exit()
target_dir = args[0]

exit_code = os.system("ts-node ./Scripts/definedOfProject.ts {}".format(target_dir))

if exit_code == 0:
    logger.debug("Project definition data successfully written.")
else:
    logger.debug(f"Project definition data written failed. code: {exit_code}")


exit_code = os.system("ts-node ./Scripts/useOfProject.ts {}".format(target_dir))

if exit_code == 0:
    logger.debug("Function usage data written successfully.")
else:
    logger.debug(f"Function usage data written failed. code:{exit_code}")

# exit_code = os.system("ts-node readProjectData.ts {}".format(target_dir))



