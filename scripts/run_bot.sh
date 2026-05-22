#!/bin/bash
export PYTHONPATH=$PYTHONPATH:.
unset REAL
export PAPER=true
./.venv/bin/python3 main_agentic_clob.py --mode PAPER
