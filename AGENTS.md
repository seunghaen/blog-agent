# AGENTS.md

## Goal

Implement pipeline 1~4 described in requirements.md.

## Non-negotiable constraints

- Output must be a complete single HTML document (head/body).
- Must not include: \*\*, emoji, <hr>, GIF, excessive formatting.
- Must not invent facts. If uncertain, phrase cautiously.
- Restaurant review usage must be limited to last 60 days only.

## Project structure

- Create modules under src/: scan_folders.py, places_client.py, vision_client.py, writer.py, rules.py, pipeline.py
- Store generated HTML under outputs/
- Optional cache under .cache/

## How to run

- Provide a CLI entry:
  python -m src.pipeline --input-root-id "<drive_folder_id>" --output-root-id "<drive_folder_id>" --latest 1

## Tests

- Add at least:
  - tests/test_folder_parse.py
  - tests/test_html_rules.py
- Running tests:
  pytest -q
