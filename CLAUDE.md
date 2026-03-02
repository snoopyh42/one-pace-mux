# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
pytest

# Run a single test class or test
pytest tests/test_onepace_mux.py::TestFindSubFile
pytest tests/test_onepace_mux.py::TestFindSubFile::test_strategy_1_prefix_match

# Lint (matches CI config)
flake8 .

# Run the script (from repo root)
python3 onepace_mux.py --output-dir /path/to/output --season 15 --dry-run
```

There is no `requirements.txt`; only stdlib is used. Install dev dependencies with `pip install pytest flake8`.

## Architecture

This is a **single-file script** (`onepace_mux.py`, ~1100 lines) with no package structure. Everything lives in one module.

### Global state

Several module-level variables are set by `main()` before any processing:
- `ONEPACE_DIR` — output library root (from `--output-dir` or `ONEPACE_DIR` env)
- `WORK_DIR` — temp download dir (default `/tmp/onepace_work`)
- `SUBS_REPO_DIR` / `SUBS_FINAL_DIR` — subtitle repo clone location (default `/tmp/onepace_subs`)
- `PIXELDRAIN_API_KEY` — optional, enables authenticated downloads

Tests that exercise path-sensitive code patch these globals via `unittest.mock.patch.object`.

### Data model

`ArcConfig` is a dataclass holding the Pixeldrain list IDs (sub + dub), resolution, and subtitle folder name for each arc. All 36 arcs are hardcoded in the `ARCS` list; `ARC_BY_SEASON` is a dict keyed by season number (1–36). When adding or updating arc data, edit `ARCS` directly.

### Two submodules, two different uses

| Submodule | Path | Used for |
|-----------|------|----------|
| `one-pace-for-plex` | `./one-pace-for-plex/` | NFO files (Plex episode metadata); copied into `--output-dir` per season |
| `one-pace-public-subtitles` | `./one-pace-public-subtitles/` | ASS subtitle files; also cloned separately at runtime to `SUBS_REPO_DIR` if submodule absent |

`ensure_subs_repo()` manages the runtime clone at `SUBS_REPO_DIR`. It uses `git clone --depth=1` and updates via `git fetch --depth=1 origin` + `git reset --hard FETCH_HEAD` (shallow, handles force-pushes). Update submodules with `git submodule update --remote`.

### Subtitle lookup (`find_sub_file`)

Four strategies tried in order:
1. Prefix match against `Final Subs/` using the Pixeldrain filename
2. Arc name + episode number match in `Final Subs/`
3. Single arc-level file in `Final Subs/` (whole-arc subs)
4. Fallback to arc folder / episode dir in the raw repo layout

### Per-arc pipeline

`process_arc()` → for each episode: `pd_download()` (sub + dub) → `find_sub_file()` → `mux_episode()` (ffmpeg) → `attach_fonts_to_mkv()` (mkvmerge, optional) → rename → cleanup.

## Lint config

`flake8`: max line length 127, max complexity 10. Submodule directories are excluded. CI enforces hard errors (`E9,F63,F7,F82`) as fail; all others are `--exit-zero`.

## Known issues

Stray `pytest-cache-files-*` directories accumulate in the repo root and inside the `one-pace-public-subtitles` submodule when pytest's `tmp_path` cleanup fails due to permission errors (typically from a previous run as a different user). Clean them with `sudo rm -rf pytest-cache-files-*` from the repo root and from `one-pace-public-subtitles/`.
