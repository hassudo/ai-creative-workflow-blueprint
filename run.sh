#!/usr/bin/env bash
# Rebuild the whole submission from source in one command.
set -euo pipefail
cd "$(dirname "$0")"
python3 pipeline/make_sample_data.py
python3 pipeline/toast_pipeline.py
python3 pipeline/build.py
echo
echo "Open index.html in a browser. Deep links: #overview #areas #toast #ideas #plan"
