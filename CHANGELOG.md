# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(No unreleased changes yet.)

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

[Unreleased]: https://github.com/snoopyh42/one-pace-mux/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/snoopyh42/one-pace-mux/releases/tag/v1.0.0
