#!/bin/bash

FILES="hsmd.py hsmd_reader.py hsmd_actions.py hsmd_step.py hsmd_components.py test/run.py"
pylint --disable=I1101,C0301,W0703 $FILES
