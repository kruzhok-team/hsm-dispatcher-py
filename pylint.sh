#!/bin/bash

FILES="hsmd.py hsmd_model.py hsmd_build.py hsmd_reader.py hsmd_actions.py hsmd_step.py hsmd_components.py hsmd_stream.py hsmd_session.py test/run.py test/stream_test.py test/session_test.py"
pylint --disable=I1101,C0301,W0703 $FILES
