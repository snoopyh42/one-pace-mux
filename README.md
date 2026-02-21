# One Pace Mux

Download and mux **One Pace** episodes from [onepace.net](https://onepace.net) into single MKV files with **dual audio** (Japanese + English dub), **AC3 audio** for Plex Direct Play, and **soft subtitles** from the official [one-pace-public-subtitles](https://github.com/one-pace/one-pace-public-subtitles) repo.

## What you get

Each output file contains:

- **Video**: H.264 (stream copy from the English Dub version for clean video, or from the Sub version when no dub exists)
- **Audio 1**: Japanese, AC3 192 kbps (default)
- **Audio 2**: English dub, AC3 192 kbps (where available)
- **Subtitles**: ASS in your chosen language (default: English; optional: German, Portuguese, Arabic, Italian, French, Spanish, Turkish, Russian)
- **Container title**: Set to the episode name so players and Plex show a proper title
- **Fonts**: Subtitle fonts are attached to the MKV (default: small set ~5.5 MB so ASS styling renders correctly; optional full set with `--full-fonts`)

## Requirements

- **Python 3.9+**
- **ffmpeg** (in your PATH)
- **git** (for recursive clone; or the script will clone the subtitle repo at runtime if the submodule is missing)
- **mkvmerge** (MKVToolNix) – optional; used to attach subtitle fonts into the MKV. If missing, the script skips font attachment and warns (mux still succeeds; ASS may not render correctly on some players).

## Getting started

### Before you start

- **Where to run:** Run the script from the repo directory (`cd one-pace-mux` after cloning) or use the **full path** to `onepace_mux.py` (e.g. `python3 /path/to/one-pace-mux/onepace_mux.py ...`).
- **Output directory:** Always pass `--output-dir` to your intended (e.g. empty) folder. If you omit it, output goes to `./One Pace` in your current directory, which may not be what you want.
- **Paths with spaces:** If your path contains spaces, put it in quotes: `--output-dir "/path/to/One Pace"`.

**Recommended workflow:** Clone this repo **recursively** so you get both submodules: [one-pace-for-plex](https://github.com/SpykerNZ/one-pace-for-plex) (NFOs) and [one-pace-public-subtitles](https://github.com/one-pace/one-pace-public-subtitles) (ASS subtitles). Run the script with an **empty** target directory. The script copies NFO files from the first submodule into your target for the requested season(s), uses the second for subtitle files (or updates it with `git pull`), then downloads and muxes so the MKVs get proper Plex names and subtitles.

```bash
git clone --recursive https://github.com/snoopyh42/one-pace-mux.git
cd one-pace-mux
# Use any empty directory as the target (e.g. a folder on your NAS or a new local folder)
python3 onepace_mux.py --output-dir /path/to/your/empty/OnePace --season 15
# Or process all arcs:
python3 onepace_mux.py --output-dir /path/to/your/empty/OnePace --all
```

The script looks for two repos next to itself: `one-pace-for-plex/One Pace/` (NFOs) and `one-pace-public-subtitles/` (ASS files in `main/Release/Final Subs`). If present, it uses them; otherwise it uses fallback episode names and, for subtitles, clones into `ONEPACE_SUBS_DIR` (default `/tmp/onepace_subs`) at runtime. **End users should clone with `--recursive`** so both submodules are present; see Submodule below.

**Without the submodules:** The script still runs: episode names fall back to e.g. `Jaya 01`, and the subtitle repo is cloned at first run if the submodule is missing.

### Submodule

- **First-time clone:** use `git clone --recursive https://github.com/snoopyh42/one-pace-mux.git`, or after a normal clone run `git submodule update --init --recursive`.
- **one-pace-for-plex:** NFO files for Plex episode titles; update with `git submodule update --remote one-pace-for-plex` (optional).
- **one-pace-public-subtitles:** ASS subtitle files; the script runs `git pull` in this dir when present. To update the submodule to latest: `git submodule update --remote one-pace-public-subtitles` (optional).

## Usage

```bash
# Process a single season (e.g. Jaya = 15, Skypiea = 16)
python3 onepace_mux.py --output-dir "/path/to/One Pace" --season 15

# Process multiple seasons
python3 onepace_mux.py --output-dir "/path/to/One Pace" --season 15 --season 16

# Process all 36 arcs (skips seasons that already have MKV files)
python3 onepace_mux.py --output-dir "/path/to/One Pace" --all

# Use German subtitles instead of English
python3 onepace_mux.py --output-dir "/path/to/One Pace" --season 15 --subtitle-lang deu

# Preview without downloading or writing files
python3 onepace_mux.py --output-dir "/path/to/One Pace" --season 4 --dry-run

# List status of all arcs
python3 onepace_mux.py --output-dir "/path/to/One Pace" --list
```

### Options

| Option | Description |
|--------|-------------|
| `--output-dir PATH` | Root of your One Pace library (default: `./One Pace` or `ONEPACE_DIR` env) |
| `--season N` | Process season N (can repeat) |
| `--all` | Process all seasons |
| `--list` | Show status (MKV/MP4 counts) per season |
| `--dry-run` | Show what would be done, no downloads or writes |
| `--force` | Overwrite existing MKV files |
| `--backup-dir PATH` | Move old MP4s here instead of deleting |
| `--subtitle-lang LANG` | Subtitle language: `eng` (default), `deu`/`de`, `por`/`pt`, `ara`/`ar`, `ita`/`it`, `fra`/`fr`, `spa`/`es`, `tur`/`tr`, `rus`/`ru` |
| `--download-delay SECS` | Pause SECS seconds between each Pixeldrain download (default: 0). Use to spread load and stay under free-tier 6 GB/24h. |
| `--no-attach-fonts` | Do not attach subtitle fonts (smaller files; ASS may not render correctly on some players). |
| `--full-fonts` | Attach full font set including Episode Fonts (~37 MB per file). Default is min set (~5.5 MB): common + OP + ED only. |
| `--debug` | Extra debug output (e.g. subtitle lookup strategy). |

### Environment (optional)

- **ONEPACE_DIR** – Default One Pace library path if `--output-dir` is not set
- **ONEPACE_WORK_DIR** – Temp directory for downloads (default: `/tmp/onepace_work`)
- **ONEPACE_SUBS_DIR** – Where to clone the subtitle repo (default: `/tmp/onepace_subs`)
- **PIXELDRAIN_API_KEY** – Your [Pixeldrain API key](https://pixeldrain.com/user/api_keys). If set, downloads use HTTP Basic auth so your **premium** account limits apply (no 6 GB/24h throttle). Keep this secret; use the env var, not the command line.

Not all arcs have every language; coverage varies (e.g. English, German, Portuguese have the widest coverage in Final Subs).

### Font attachment

By default the script attaches a **min** font set (~5.5 MB) from the subtitle repo (Common + Opening + Ending fonts) so ASS styling (signs, karaoke, typesetting) renders correctly in players that use embedded fonts. Use `--full-fonts` to attach the full set including Episode Fonts (~37 MB per file) for maximum compatibility. Use `--no-attach-fonts` to skip font attachment and keep files smaller (ASS may fall back to system fonts and look wrong). Requires **mkvmerge** (MKVToolNix); if not installed, the script skips attachment and warns.

### Testing

Tests are in `tests/` and use [pytest](https://pytest.org). From the repo root:

```bash
pip install pytest
pytest
```

CI (GitHub Actions) runs lint (flake8) and tests on push and pull request to `main` for Python 3.9, 3.10, and 3.11.

### Troubleshooting

- **"can't open file 'onepace_mux.py'"** — You're not in the repo directory. Run `cd one-pace-mux` first, or use the full path to the script.
- **"unrecognized arguments" when using `--output-dir`** — Your path contains spaces; put it in quotes: `--output-dir "/path/to/One Pace"`.
- **Episode names like "Jaya 01" instead of full titles** — You didn't clone with submodules. Run `git clone --recursive ...` or, if already cloned, `git submodule update --init --recursive`.
- **ffmpeg or mux errors** — Ensure `ffmpeg` is installed and on your PATH (`which ffmpeg`).
- **"mkvmerge not found; skipping font attachment"** — Optional. Install MKVToolNix for your OS so `mkvmerge` is on your PATH if you want fonts embedded; otherwise the script still muxes, but ASS may not render correctly on some players.
- **Downloads very slow or "speed limited"** — Pixeldrain’s free tier has a **6 GB per 24 hours** (sliding window) limit per IP. Once you exceed it, they throttle download speed. Options: wait for the window to roll off, use a different network/VPN (new IP), or use Pixeldrain premium. You can also use `--download-delay N` to space downloads and spread usage over time.
- **I have Pixeldrain premium but I’m still throttled** — Set **PIXELDRAIN_API_KEY** to your [API key](https://pixeldrain.com/user/api_keys) (e.g. `export PIXELDRAIN_API_KEY=your-key`) so downloads are authenticated and use your account’s premium limits instead of IP-based free limits.

## Folder structure

Your `--output-dir` will contain `Season 1/` … `Season 36/`. When you use the recommended workflow (clone with `--recursive`), the script copies episode NFOs from the submodule into these season folders, then writes MKVs with matching names (e.g. `One Pace - S15E01 - Why the Log Pose Is Spherical.mkv`). The script downloads from Pixeldrain (onepace.net links), matches episodes by season/episode number, and writes MKVs alongside the NFOs. Existing MP4s are removed unless you use `--backup-dir`.

## Credits and disclaimer

- **[One Pace](https://onepace.net)** – Fan edit and releases; all video/audio sources are from their official Pixeldrain links.
- **[one-pace-public-subtitles](https://github.com/one-pace/one-pace-public-subtitles)** – Official subtitle repository used for ASS tracks.
- **Pixeldrain** – Host for One Pace file lists and downloads.

This tool is **unofficial** and for **personal use**. Use it only with content you obtain in line with One Pace's and the rights holders' terms. Obtain content only through lawful means; this project does not encourage infringement of copyright or other rights. The script does not host or redistribute any media; it only downloads from public One Pace links and muxes them locally.

This project does not grant any rights to the underlying content (e.g. One Piece anime, One Pace edits, or subtitles). All such content remains the property of its respective rights holders; use only in accordance with their terms and applicable law.

One Pace, One Piece, Plex, and other names used here are trademarks or registered trademarks of their respective owners. This project is not affiliated with or endorsed by them.

The authors and contributors are not responsible for how you use this tool or for your compliance with copyright, trademark, or other laws.

## License

MIT License. See [LICENSE](LICENSE).
