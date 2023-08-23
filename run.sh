#!/bin/bash

SCRIPTDIR=$(cd $(dirname $0) > /dev/null 2>&1 && pwd)

pushd $SCRIPTDIR > /dev/null
source venv/bin/activate
python3 se_battery_control.py x.x.x.x
popd > /dev/null
