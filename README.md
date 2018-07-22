# Docdiffer

A tool for figuring out what changed in your DRF API code between versions.

# Usage

1. In the code repository where your API lives, pull the latest code from your remote branch and check out the latest code changes. e.g. current release branch.
2. Run `python path/to/docdiffer.py --branch=<previous_release_branch> --root=.`.
