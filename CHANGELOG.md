# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(No unreleased changes yet.)

## [1.1.1] - 2025-02-21

### Added

- **Dependency check with install offer**: At startup the script checks for `ffmpeg` (required) and `mkvmerge` (optional). If missing and stdin is a TTY, it offers to run the platform-appropriate install command (e.g. `sudo apt install ffmpeg`, `brew install ffmpeg` on macOS, Chocolatey/winget on Windows).
- **`--copy-nfo-only`**: Copy NFO files from one-pace-for-plex into the output dir and exit (no download/mux). Use after updating the submodule to refresh NFOs for all or selected seasons.
- **Retry with exponential backoff**: Pixeldrain list and download requests retry up to 3 times (2s, 4s delays) on failure.
- **Request timeout**: All Pixeldrain HTTP requests use a 30-second timeout to avoid indefinite hangs.
- **Logging**: Replaced `print` with the `logging` module; use `--debug` for verbose output.
- **Unit tests**: Tests for subtitle lookup strategies, mux dry-run, and download caching (pytest).

### Changed

- **NFO copy timing**: NFOs are now copied when **each season starts** processing (in `process_arc`), not once upfront. Ensures updated submodule content is used and interrupted runs don’t leave later seasons without NFOs.
- **Work directory**: `WORK_DIR` is created with mode `0o700` when it doesn’t exist.
- **Subtitle lookup**: `find_sub_file()` refactored into smaller helpers (`_match_sub_by_prefix`, `_match_sub_by_arc_ep`, etc.) for clarity and testability.

### Fixed

- (No bug fixes in this release.)

### Documentation

- **Sudo/admin clarification**: Docstrings and README now state that on Linux the dependency install command uses sudo and that administrative access is only needed if the user accepts the install offer. Test docstring notes that installs are mocked and no sudo/admin is required to run tests.

## [1.1.0] - 2025-02-21

### Added

- **Container title**: MKV container title is set to the episode name (e.g. Plex episode title) so players and Plex show a proper title instead of the filename.
- **Font attachment**: Subtitle fonts from the one-pace-public-subtitles repo are attached to each MKV via mkvmerge (MKVToolNix) so ASS styling (signs, karaoke, typesetting) renders correctly. Default uses a **min** set (~5.5 MB): Common + Opening + Ending fonts only.
- **`--full-fonts`**: Attach the full font set including Episode Fonts (~37 MB per file) for maximum compatibility with all episode-specific styling.
- **`--no-attach-fonts`**: Disable font attachment for smaller files (ASS may not render correctly on some players).
- README: Font attachment section, mkvmerge requirement (optional), new options and troubleshooting.

### Changed

- Font attachment is optional: if mkvmerge is not found, the script warns and skips attachment instead of failing.

## [1.0.0] - 2025-02-20

### Added

- Initial release of `onepace_mux.py`: download One Pace episodes from Pixeldrain and mux to single MKV files.
- Dual audio: Japanese (from Sub) + English dub (from Dub), both transcoded to AC3 192 kbps for Plex Direct Play.
- H.264 video stream copy (from Dub when available, else Sub).
- Soft ASS subtitles from [one-pace-public-subtitles](https://github.com/one-pace/one-pace-public-subtitles); default English, optional German, Portuguese, Arabic, Italian, French, Spanish, Turkish, Russian (`--subtitle-lang`).
- Optional submodules: [one-pace-for-plex](https://github.com/SpykerNZ/one-pace-for-plex) (NFOs for Plex episode names) and one-pace-public-subtitles (ASS files). Script copies NFOs into an empty `--output-dir` for requested season(s), then downloads and muxes.
- CLI: `--output-dir`, `--season`, `--all`, `--list`, `--dry-run`, `--force`, `--backup-dir`, `--subtitle-lang`. Env: `ONEPACE_DIR`, `ONEPACE_WORK_DIR`, `ONEPACE_SUBS_DIR`.
- README: Getting started, Before you start, Troubleshooting, legal/trademark disclaimers.
- Robustness: hardened Pixeldrain API parsing, `git pull` failure handling, safe cleanup on move failure, download error reporting, fail-fast if subtitle dir missing.

### Fixed

- FFmpeg output path was incorrectly passed as metadata; now passed as the final output file argument.

[Unreleased]: https://github.com/snoopyh42/one-pace-mux/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/snoopyh42/one-pace-mux/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/snoopyh42/one-pace-mux/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/snoopyh42/one-pace-mux/releases/tag/v1.0.0
