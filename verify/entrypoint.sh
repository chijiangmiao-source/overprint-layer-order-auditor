#!/bin/sh
# One-shot verify entrypoint: unit tests first, then live acceptance.
set -e

echo "########## 1/2 backend unit + exhaustive DP tests ##########"
python -m pytest -q

echo
echo "########## 2/2 live end-to-end acceptance (web + api) ##########"
python acceptance.py
