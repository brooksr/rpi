"""Fill @@NAME@@ placeholders in a staged install tree from the environment.

Personal values (home coordinates, street, circuit, ...) live in the repo's
gitignored .env, which config.sh exports. Fails if any placeholder is unset so
a half-rendered file never reaches Home Assistant.

Usage: python3 render_env.py STAGE_DIR
"""
import os
import pathlib
import re
import sys

PLACEHOLDER = re.compile(r'@@([A-Z][A-Z0-9_]*)@@')


def main():
    missing = set()
    for path in pathlib.Path(sys.argv[1]).rglob('*'):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if '@@' not in text:
            continue

        def fill(match):
            value = os.environ.get(match.group(1))
            if not value:
                missing.add(match.group(1))
                return match.group(0)
            return value

        path.write_text(PLACEHOLDER.sub(fill, text))
    if missing:
        sys.exit('Set these in .env (see .env.example): ' + ', '.join(sorted(missing)))


if __name__ == '__main__':
    main()
