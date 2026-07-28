"""Test-suite setup.

AlphaSimR was installed to ~/R/library on this machine, which is not one of R's
default library paths. R reads R_LIBS_USER at startup, so it has to be set before
rpy2 initialises R — hence here, at collection time, rather than inside a test.
"""

import os

_USER_R_LIB = os.path.expanduser("~/R/library")
if os.path.isdir(_USER_R_LIB):
    existing = os.environ.get("R_LIBS_USER", "")
    if _USER_R_LIB not in existing.split(os.pathsep):
        os.environ["R_LIBS_USER"] = (
            f"{_USER_R_LIB}{os.pathsep}{existing}" if existing else _USER_R_LIB
        )
