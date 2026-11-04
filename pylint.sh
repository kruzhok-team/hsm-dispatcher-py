#!/bin/bash

FILES="hsmd test/run.py test/stream_test.py test/session_test.py"
pylint --disable=I1101,C0301,W0703 $FILES
