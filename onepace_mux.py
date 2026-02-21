#!/usr/bin/env python3
"""
One Pace Download & Mux Script

Downloads English Sub and English Dub versions from Pixeldrain, fetches official
ASS subtitles from GitHub, and muxes them into optimized MKV files with:
  - H.264 video (stream copy from Dub version for clean video, or Sub if no dub)
  - Japanese AC3 192k audio (from Sub version)
  - English AC3 192k audio (from Dub version, where available)
  - English ASS subtitles (from one-pace-public-subtitles GitHub repo)
  - Subtitle fonts attached to the MKV (via mkvmerge) so ASS styling renders correctly

Processes one arc (season) at a time, episode by episode, to minimize temp disk usage.
Requires: ffmpeg; mkvmerge (MKVToolNix) for font attachment (optional, will skip if missing).
"""

import argparse
import base64
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Request timeout (seconds) for Pixeldrain API and downloads
PD_REQUEST_TIMEOUT = 30
# Retry attempts and base delay for exponential backoff (seconds)
PD_RETRY_ATTEMPTS = 3
PD_RETRY_BASE_DELAY = 2

log = logging.getLogger("onepace_mux")

# ---------------------------------------------------------------------------
# Configuration (overridable via environment or --output-dir)
# ---------------------------------------------------------------------------

# Set in main() from --output-dir and env (ONEPACE_DIR, ONEPACE_WORK_DIR, ONEPACE_SUBS_DIR, PIXELDRAIN_API_KEY)
ONEPACE_DIR: Path = Path("One Pace")
PIXELDRAIN_API_KEY: Optional[str] = None  # When set, downloads use HTTP Basic auth so premium limits apply
WORK_DIR: Path = Path("/tmp/onepace_work")
SUBS_REPO_DIR: Path = Path("/tmp/onepace_subs")
SUBS_FINAL_DIR: Path = Path("/tmp/onepace_subs/main/Release/Final Subs")

SUBS_REPO_URL = "https://github.com/one-pace/one-pace-public-subtitles.git"
PIXELDRAIN_API = "https://pixeldrain.com/api"
AC3_BITRATE = "192k"

# Debug logging (set by --debug)
DEBUG = False


def _debug(msg: str, *args: object) -> None:
    if DEBUG:
        log.debug(msg, *args)


# Subtitle language: (Final Subs filename suffix before .ass, arc-folder suffix e.g. "en.ass")
# English = no suffix in Final Subs; others match e.g. " Deutsch.ass", " Arabic.ass"
SUBTITLE_LANGS = {
    "eng": ("", "en"),
    "en": ("", "en"),
    "deu": (" Deutsch", "de"),
    "de": (" Deutsch", "de"),
    "deutsch": (" Deutsch", "de"),
    "ger": (" Deutsch", "de"),
    "por": (" Portugues", "pt"),
    "pt": (" Portugues", "pt"),
    "portugues": (" Portugues", "pt"),
    "ara": (" Arabic", "ar"),
    "ar": (" Arabic", "ar"),
    "arabic": (" Arabic", "ar"),
    "ita": (" Italian", "it"),
    "it": (" Italian", "it"),
    "italian": (" Italian", "it"),
    "fra": (" French", "fr"),
    "fr": (" French", "fr"),
    "french": (" French", "fr"),
    "spa": (" Spanish", "es"),
    "es": (" Spanish", "es"),
    "spanish": (" Spanish", "es"),
    "tur": (" Turkish", "tr"),
    "tr": (" Turkish", "tr"),
    "turkish": (" Turkish", "tr"),
    "rus": (" Russian", "ru"),
    "ru": (" Russian", "ru"),
    "russian": (" Russian", "ru"),
}


# ISO 639-2 code and display name for subtitle track metadata (first key per language wins)
SUBTITLE_LANG_META = {
    "eng": ("eng", "English"), "en": ("eng", "English"),
    "deu": ("deu", "German"), "de": ("deu", "German"), "deutsch": ("deu", "German"), "ger": ("deu", "German"),
    "por": ("por", "Portuguese"), "pt": ("por", "Portuguese"), "portugues": ("por", "Portuguese"),
    "ara": ("ara", "Arabic"), "ar": ("ara", "Arabic"), "arabic": ("ara", "Arabic"),
    "ita": ("ita", "Italian"), "it": ("ita", "Italian"), "italian": ("ita", "Italian"),
    "fra": ("fra", "French"), "fr": ("fra", "French"), "french": ("fra", "French"),
    "spa": ("spa", "Spanish"), "es": ("spa", "Spanish"), "spanish": ("spa", "Spanish"),
    "tur": ("tur", "Turkish"), "tr": ("tur", "Turkish"), "turkish": ("tur", "Turkish"),
    "rus": ("rus", "Russian"), "ru": ("rus", "Russian"), "russian": ("rus", "Russian"),
}


@dataclass
class ArcConfig:
    name: str
    season: int
    sub_id: str  # Pixeldrain list ID for English Sub (best resolution)
    dub_id: Optional[str] = None  # Pixeldrain list ID for English Dub (best resolution)
    sub_res: str = "720p"
    dub_res: str = "720p"
    arc_folder: Optional[str] = None  # Folder name in subtitle repo (e.g., "14 Skypiea")


ARCS = [
    ArcConfig("Romance Dawn",        1,  "LVyeVAjL", "bypZ611Y", "1080p", "1080p", "01 Romance Dawn"),
    ArcConfig("Orange Town",         2,  "MAwZejPC", "bViNuyND", "1080p", "1080p", "02 Orange Town"),
    ArcConfig("Syrup Village",       3,  "bZughUL3", "rwKsdYhv", "1080p", "1080p", "03 Syrup Village"),
    ArcConfig("Gaimon",              4,  "34RuaDWW", "UqmPsUCF", "1080p", "1080p", "04 Gaimon"),
    ArcConfig("Baratie",             5,  "DvABXt6w", "tJVhNxyK", "1080p", "1080p", "05 Baratie"),
    ArcConfig("Arlong Park",         6,  "7zXoKGrW", "6DatxPiL", "1080p", "1080p", "06 Arlong Park"),
    ArcConfig("Buggy's Crew",        7,  "E1QXSY7a", "z5hJ3bZ9", "720p",  "720p",  "07 The Adventures of Buggy's Crew"),
    ArcConfig("Loguetown",           8,  "sng6aHYQ", "6PXc5Fwt", "480p",  "480p",  "08 Loguetown"),
    ArcConfig("Reverse Mountain",    9,  "gehq5RGo", "np7wZkqg", "720p",  "720p",  "09 Reverse Mountain"),
    ArcConfig("Whisky Peak",         10, "5d4WRz1y", None,        "480p",  "",      "10 Whisky Peak"),
    ArcConfig("Koby-Meppo",          11, "81KWfWcq", "HfHjHtvU", "720p",  "720p",  "11 The Trials of Koby-Meppo"),
    ArcConfig("Little Garden",       12, "NBMcTurd", "dokMzV7s", "1080p", "1080p", "12 Little Garden"),
    ArcConfig("Drum Island",         13, "4juJksu7", "uHcgEuGE", "720p",  "720p",  "13 Drum Island"),
    ArcConfig("Alabasta",            14, "KX3E2PR4", "eyh7yEiv", "1080p", "1080p", "14 Alabasta"),
    ArcConfig("Jaya",                15, "P6mnmZpN", "KkaKPKG5", "720p",  "720p",  "15 Jaya"),
    ArcConfig("Skypiea",             16, "arhxWEdj", "TVGUu2hh", "1080p", "1080p", "14 Skypiea"),
    ArcConfig("Long Ring Long Land", 17, "naP4DUTn", "KDhJiGow", "1080p", "1080p", "16 Long Ring Long Land"),
    ArcConfig("Water Seven",         18, "o8YkGt9i", "YASfiy9a", "720p",  "720p",  "17 Water Seven"),
    ArcConfig("Enies Lobby",         19, "Lbggw3VT", "AaZZzDQ6", "1080p", "1080p", "18 Enies Lobby"),
    ArcConfig("Post-Enies Lobby",    20, "upyN5vVk", None,        "720p",  "",      "19 Post-Enies Lobby"),
    ArcConfig("Thriller Bark",       21, "Cq9faLGv", None,        "720p",  "",      "20 Thriller Bark"),
    ArcConfig("Sabaody Archipelago", 22, "jhpKUqF8", None,        "720p",  "",      "21 Sabaody Archipelago"),
    ArcConfig("Amazon Lily",         23, "Bsr9gKsn", None,        "720p",  "",      "22 Amazon Lily"),
    ArcConfig("Impel Down",          24, "y5ywnHdF", None,        "720p",  "",      "23 Impel Down"),
    ArcConfig("Straw Hat Adventures", 25, "cnjWovN9", "Ua5GkcGr", "720p", "720p", "24 If You Could Go Anywhere"),
    ArcConfig("Marineford",          26, "uFuFpnpi", None,        "720p",  "",      "25 Marineford"),
    ArcConfig("Post-War",            27, "7EANMSA7", "tEnZhUuP", "720p",  "720p",  "26 Post-War"),
    ArcConfig("Return to Sabaody",   28, "igysH62b", "ED8gfT3e", "720p",  "720p",  "27 Return to Sabaody"),
    ArcConfig("Fishman Island",      29, "o6ZzNwzp", None,        "720p",  "",      "28 Fishman Island"),
    ArcConfig("Punk Hazard",         30, "wJoipMZu", None,        "720p",  "",      "29 Punk Hazard"),
    ArcConfig("Dressrosa",           31, "DMuj2Pqe", None,        "720p",  "",      "30 Dressrosa"),
    ArcConfig("Zou",                 32, "nSkEY2Cq", None,        "720p",  "",      "31 Zou"),
    ArcConfig("Whole Cake Island",   33, "phsTwRmF", None,        "720p",  "",      "32 Whole Cake Island"),
    ArcConfig("Reverie",             34, "RLz2BXe7", "Cp4KrdKb", "1080p", "1080p", "33 Reverie"),
    ArcConfig("Wano",                35, "iRATbpNF", "NADiYYhV", "1080p", "1080p", "34 Wano"),
    ArcConfig("Egghead",             36, "ddzH3mPn", "nKaeVsMp", "1080p", "1080p", "35 Egghead"),
]

ARC_BY_SEASON = {a.season: a for a in ARCS}


# ---------------------------------------------------------------------------
# Dependency check (ffmpeg required; mkvmerge optional for font attachment)
# ---------------------------------------------------------------------------

def _get_install_command(tool: str) -> Optional[list[str]]:  # noqa: C901
    """Return the shell command to install the given tool, or None if unknown.
    tool is 'ffmpeg' or 'mkvmerge' (mkvtoolnix package).
    """
    system = platform.system()
    if system == "Linux":
        # Prefer apt-get (Debian/Ubuntu), then dnf (Fedora), pacman (Arch), zypper (openSUSE)
        if shutil.which("apt-get"):
            pkg = "ffmpeg" if tool == "ffmpeg" else "mkvtoolnix"
            return ["sudo", "apt-get", "install", "-y", pkg]
        if shutil.which("dnf"):
            pkg = "ffmpeg" if tool == "ffmpeg" else "mkvtoolnix"
            return ["sudo", "dnf", "install", "-y", pkg]
        if shutil.which("pacman"):
            pkg = "ffmpeg" if tool == "ffmpeg" else "mkvtoolnix"
            return ["sudo", "pacman", "-S", "--noconfirm", pkg]
        if shutil.which("zypper"):
            pkg = "ffmpeg" if tool == "ffmpeg" else "mkvtoolnix"
            return ["sudo", "zypper", "install", "-y", pkg]
        return None
    if system == "Darwin":
        if shutil.which("brew"):
            pkg = "ffmpeg" if tool == "ffmpeg" else "mkvtoolnix"
            return ["brew", "install", pkg]
        return None
    if system == "Windows":
        if shutil.which("choco"):
            pkg = "ffmpeg" if tool == "ffmpeg" else "mkvtoolnix"
            return ["choco", "install", "-y", pkg]
        if shutil.which("winget"):
            pkg = "ffmpeg" if tool == "ffmpeg" else "GnuWin32.MKVToolNix"
            return ["winget", "install", "--accept-package-agreements", pkg]
        return None
    return None


def ensure_dependencies(offer_install: bool = True, dry_run: bool = False) -> None:  # noqa: C901
    """Check that ffmpeg (required) and mkvmerge (optional) are available.
    If missing and offer_install is True and stdin is a TTY, offer to run the
    platform-appropriate install command. On Linux the command uses sudo;
    administrative access is only needed if you accept the install offer.
    """
    if dry_run:
        return
    missing_ffmpeg = not shutil.which("ffmpeg")
    missing_mkvmerge = not shutil.which("mkvmerge")
    if not missing_ffmpeg and not missing_mkvmerge:
        return

    can_prompt = sys.stdin.isatty()
    if missing_ffmpeg:
        cmd = _get_install_command("ffmpeg")
        cmd_str = " ".join(cmd) if cmd else "your package manager"
        log.error("ffmpeg is required but not found. Install with: %s", cmd_str)
        if offer_install and can_prompt and cmd:
            try:
                reply = input("Attempt to install ffmpeg now? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                reply = "n"
            if reply == "y" or reply == "yes":
                log.info("Running: %s", cmd_str)
                result = subprocess.run(cmd, stdin=sys.stdin)
                if result.returncode != 0:
                    log.error("Install command failed (exit %d). Install ffmpeg manually and re-run.", result.returncode)
                    sys.exit(1)
                log.info("ffmpeg installed successfully.")
            else:
                log.error("ffmpeg is required. Exiting.")
                sys.exit(1)
        elif missing_ffmpeg:
            sys.exit(1)

    if missing_mkvmerge:
        cmd = _get_install_command("mkvmerge")
        cmd_str = " ".join(cmd) if cmd else "your package manager (e.g. mkvtoolnix)"
        log.warning("mkvmerge not found; font attachment will be skipped. Install with: %s", cmd_str)
        if offer_install and can_prompt and cmd:
            try:
                reply = input("Attempt to install mkvtoolnix now? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                reply = "n"
            if reply == "y" or reply == "yes":
                log.info("Running: %s", cmd_str)
                result = subprocess.run(cmd, stdin=sys.stdin)
                if result.returncode != 0:
                    log.warning("Install command failed (exit %d). Font attachment will be skipped.", result.returncode)
                else:
                    log.info("mkvtoolnix installed successfully.")


# ---------------------------------------------------------------------------
# Pixeldrain helpers
# ---------------------------------------------------------------------------

@dataclass
class PdFile:
    file_id: str
    name: str
    size: int
    episode_num: int = 0


def _urlopen_with_retry(req: urllib.request.Request, timeout: int = PD_REQUEST_TIMEOUT):
    """Open URL with timeout and exponential backoff retry."""
    last_error = None
    for attempt in range(PD_RETRY_ATTEMPTS):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            last_error = e
            if attempt < PD_RETRY_ATTEMPTS - 1:
                delay = PD_RETRY_BASE_DELAY ** attempt
                log.warning("  Request failed (attempt %d/%d), retrying in %ds: %s",
                            attempt + 1, PD_RETRY_ATTEMPTS, delay, e)
                time.sleep(delay)
    raise last_error


def pd_list_files(list_id: str) -> list[PdFile]:
    """Query Pixeldrain API and return file list for a given list ID."""
    url = f"{PIXELDRAIN_API}/list/{list_id}"
    req = urllib.request.Request(url)
    with _urlopen_with_retry(req) as resp:
        data = json.loads(resp.read())
    if not data.get("success", False):
        raise RuntimeError(f"Pixeldrain API error for list {list_id}: {data}")
    files = []
    for f in data.get("files", []):
        if not isinstance(f, dict) or "id" not in f or "name" not in f or "size" not in f:
            continue
        pf = PdFile(file_id=f["id"], name=f["name"], size=f["size"])
        ep_match = re.search(r'\b(\d{2})\s*\[', pf.name)
        if not ep_match:
            ep_match = re.search(r'\s(\d{2})\s', pf.name)
        if ep_match:
            pf.episode_num = int(ep_match.group(1))
        files.append(pf)
    return sorted(files, key=lambda f: f.episode_num)


def pd_download(file_id: str, dest: Path, expected_size: int = 0) -> Path:
    """Download a file from Pixeldrain with progress display.
    If PIXELDRAIN_API_KEY is set, uses HTTP Basic auth so your premium account limits apply.
    """
    url = f"{PIXELDRAIN_API}/file/{file_id}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and expected_size > 0 and dest.stat().st_size == expected_size:
        log.info("    [skip] Already downloaded: %s", dest.name)
        return dest

    log.info("    Downloading %s (%.1f MB)...", dest.name, expected_size / 1024 / 1024)
    start = time.time()

    req = urllib.request.Request(url)
    if PIXELDRAIN_API_KEY:
        # Pixeldrain: Basic auth with empty username and API key as password
        credentials = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
        req.add_header("Authorization", f"Basic {credentials}")

    last_error = None
    for attempt in range(PD_RETRY_ATTEMPTS):
        try:
            resp = _urlopen_with_retry(req)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            last_error = e
            if attempt < PD_RETRY_ATTEMPTS - 1:
                delay = PD_RETRY_BASE_DELAY ** attempt
                log.warning("    Download failed (attempt %d/%d), retrying in %ds: %s",
                            attempt + 1, PD_RETRY_ATTEMPTS, delay, e)
                time.sleep(delay)
            else:
                log.error("    [ERROR] Download failed: %s for %s", e, dest.name)
                raise last_error

    with resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0)) or expected_size
        downloaded = 0
        chunk_size = 1024 * 1024  # 1 MB
        last_print = start
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            now = time.time()
            if now - last_print > 2:
                pct = (downloaded / total * 100) if total else 0
                speed = downloaded / (now - start) / 1024 / 1024
                log.info("    Downloading %s (%.1f MB)... %.0f%% @ %.1f MB/s",
                         dest.name, expected_size / 1024 / 1024, pct, speed)
                last_print = now

    elapsed = time.time() - start
    speed = (expected_size or downloaded) / elapsed / 1024 / 1024 if elapsed > 0 else 0
    log.info("    Downloaded %s (%.1f MB) in %.0fs (%.1f MB/s)", dest.name,
             expected_size / 1024 / 1024, elapsed, speed)
    return dest

# ---------------------------------------------------------------------------
# Subtitle helpers
# ---------------------------------------------------------------------------


def ensure_subs_repo():
    """Clone or update the subtitle repository."""
    if SUBS_REPO_DIR.exists() and (SUBS_REPO_DIR / ".git").exists():
        log.info("  Updating subtitle repository...")
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=SUBS_REPO_DIR,
            capture_output=True,
            timeout=60,
            text=True,
        )
        if result.returncode != 0:
            log.error("Subtitle repo update failed (git pull exited %d).", result.returncode)
            if result.stderr:
                log.error("%s", result.stderr.strip())
            log.error("  Fix the repo (e.g. resolve conflicts) or remove it and re-run so it can clone fresh.")
            sys.exit(1)
        return
    log.info("  Cloning subtitle repository (one-time)...")
    if SUBS_REPO_DIR.exists():
        shutil.rmtree(SUBS_REPO_DIR)
    subprocess.run(
        ["git", "clone", "--depth", "1", SUBS_REPO_URL, str(SUBS_REPO_DIR)],
        check=True, timeout=300)
    log.info("  Subtitle repository ready.")


def _sub_lang_ok(f: Path, want_english: bool, non_english_lang: str, final_suffix: str) -> bool:
    """Return True if ASS path f passes language filter for Final Subs."""
    if not f.name.endswith(".ass"):
        return False
    if want_english:
        if re.search(rf'{non_english_lang}\s*\.ass$', f.name, re.IGNORECASE):
            return False
        if re.search(rf'{non_english_lang}\s+(Extended|Alternate)', f.name, re.IGNORECASE):
            return False
        return True
    if not f.name.endswith(final_suffix + ".ass"):
        return False
    ext_alt = re.search(r'\s+(Extended|Alternate)\s*\.ass$', f.name, re.IGNORECASE)
    if ext_alt and final_suffix + " Extended" not in f.name and final_suffix + " Alternate" not in f.name:
        return False
    return True


def _match_sub_by_prefix(
    prefix: str,
    final_dir: Path,
    want_english: bool,
    non_english_lang: str,
    final_suffix: str,
) -> Optional[Path]:
    """Strategy 1: Match by chapter+arc+number prefix in Final Subs."""
    for f in final_dir.iterdir():
        if not _sub_lang_ok(f, want_english, non_english_lang, final_suffix):
            continue
        if f.name.startswith(prefix):
            return f
    return None


def _match_sub_by_arc_ep(
    arc_name: str,
    episode_num: int,
    final_dir: Path,
    want_english: bool,
    non_english_lang: str,
    final_suffix: str,
) -> Optional[Path]:
    """Strategy 2: Match by arc name + episode number in Final Subs."""
    arc_name_pattern = arc_name.replace("'", ".")
    for f in sorted(final_dir.iterdir()):
        if not _sub_lang_ok(f, want_english, non_english_lang, final_suffix):
            continue
        if re.search(rf'{arc_name_pattern}\s+0*{episode_num}\b', f.name, re.IGNORECASE):
            return f
    return None


def _match_sub_by_arc_single(
    arc_name: str,
    final_dir: Path,
    want_english: bool,
    non_english_lang: str,
    final_suffix: str,
) -> Optional[Path]:
    """Strategy 3: Match by arc name only when exactly one file matches (whole-arc sub)."""
    arc_name_flex = re.sub(r"[-'\s]+", r"[\\s'-]*", re.escape(arc_name))
    arc_name_re = re.compile(rf'\b{arc_name_flex}\b', re.IGNORECASE)
    matches = [
        f for f in sorted(final_dir.iterdir())
        if _sub_lang_ok(f, want_english, non_english_lang, final_suffix) and arc_name_re.search(f.name)
    ]
    return matches[0] if len(matches) == 1 else None


def _match_sub_by_folder_desc(
    arc_folder: str,
    final_dir: Path,
    want_english: bool,
    non_english_lang: str,
    final_suffix: str,
) -> Optional[Path]:
    """Strategy 3b: Match by arc_folder description only when exactly one file matches."""
    folder_desc = re.sub(r"^\d+\s+", "", arc_folder).strip()
    if not folder_desc:
        return None
    desc_flex = re.sub(r"[-'\s]+", r"[\\s'-]*", re.escape(folder_desc))
    desc_re = re.compile(rf'\b{desc_flex}\b', re.IGNORECASE)
    matches = [
        f for f in sorted(final_dir.iterdir())
        if _sub_lang_ok(f, want_english, non_english_lang, final_suffix) and desc_re.search(f.name)
    ]
    return matches[0] if len(matches) == 1 else None


def _match_sub_by_arc_folder(  # noqa: C901
    arc: ArcConfig,
    episode_num: int,
    arc_suffix: str,
    subs_repo_dir: Path,
) -> Optional[Path]:
    """Strategy 4: Fall back to arc episode folder in repo (e.g. 14 Skypiea/24/skypiea 24 en.ass)."""
    main_dir = subs_repo_dir / "main"
    if not main_dir.exists():
        return None
    arc_folder_candidates = []
    if arc.arc_folder and (main_dir / arc.arc_folder).exists():
        arc_folder_candidates.append(arc.arc_folder)
    arc_name_simple = arc.name.replace("'", "").replace("-", " ")
    for d in main_dir.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if arc.name in d.name or arc_name_simple in d.name.replace("-", " "):
            if d.name not in arc_folder_candidates:
                arc_folder_candidates.append(d.name)
    for folder_name in arc_folder_candidates:
        arc_dir = main_dir / folder_name / f"{episode_num:02d}"
        if not arc_dir.exists():
            arc_dir = main_dir / folder_name / str(episode_num)
        if not arc_dir.exists():
            continue
        candidates = [
            f for f in sorted(arc_dir.iterdir())
            if f.name.endswith(f" {arc_suffix}.ass")
        ]
        if not candidates:
            continue
        non_alt = [f for f in candidates if "alternate" not in f.name.lower()]
        return non_alt[0] if non_alt else candidates[0]
    return None


def find_sub_file(
    arc: ArcConfig, episode_num: int, pd_filename: str, subtitle_lang: str = "eng"
) -> Optional[Path]:
    """Find the matching ASS subtitle file for an episode in the requested language.

    Search strategy:
    1. Match by Pixeldrain filename pattern in Final Subs
    2. Match by arc name + episode number in Final Subs
    3. Match by arc name only (one sub file for whole arc, e.g. Buggy's Crew, Koby-Meppo)
    3b. Match by arc_folder description (e.g. "If You Could Go Anywhere")
    4. Fall back to arc episode folder in repo for per-episode subs
    """
    lang_key = subtitle_lang.strip().lower()
    final_suffix, arc_suffix = SUBTITLE_LANGS.get(lang_key, ("", "en"))
    want_english = final_suffix == ""
    non_english_lang = r'(Deutsch|Arabic|Italian|Portugues|French|Spanish|Turkish|Russian|Polish)'

    base_match = re.match(r'(\[One Pace\]\[.*?\]\s+\S+.*?\s+\d+)', pd_filename)

    if base_match:
        found = _match_sub_by_prefix(
            base_match.group(1), SUBS_FINAL_DIR, want_english, non_english_lang, final_suffix
        )
        if found:
            _debug("sub Strategy 1 (prefix): %s", found.name)
            return found

    found = _match_sub_by_arc_ep(
        arc.name, episode_num, SUBS_FINAL_DIR, want_english, non_english_lang, final_suffix
    )
    if found:
        _debug("sub Strategy 2 (arc+ep): %s", found.name)
        return found

    found = _match_sub_by_arc_single(
        arc.name, SUBS_FINAL_DIR, want_english, non_english_lang, final_suffix
    )
    if found:
        _debug("sub Strategy 3 (arc name, single file): %s", found.name)
        return found

    if arc.arc_folder:
        found = _match_sub_by_folder_desc(
            arc.arc_folder, SUBS_FINAL_DIR, want_english, non_english_lang, final_suffix
        )
        if found:
            _debug("sub Strategy 3b (arc_folder desc, single file): %s", found.name)
            return found

    found = _match_sub_by_arc_folder(arc, episode_num, arc_suffix, SUBS_REPO_DIR)
    if found:
        _debug("sub Strategy 4 (arc folder): %s", found.name)
        return found

    _debug("no sub (arc=%r ep=%s pd=%r)", arc.name, episode_num, pd_filename)
    return None

# ---------------------------------------------------------------------------
# NFO / Plex naming helpers
# ---------------------------------------------------------------------------


def get_nfo_source_dir() -> Optional[Path]:
    """Return the one-pace-for-plex 'One Pace' directory next to this script, or None if missing."""
    script_dir = Path(__file__).resolve().parent
    nfo_source = script_dir / "one-pace-for-plex" / "One Pace"
    return nfo_source if nfo_source.is_dir() else None


def get_subs_source_dir() -> Optional[Path]:
    """Return the one-pace-public-subtitles repo directory next to this script, or None if missing."""
    script_dir = Path(__file__).resolve().parent
    subs_source = script_dir / "one-pace-public-subtitles"
    final_subs = subs_source / "main" / "Release" / "Final Subs"
    return subs_source.resolve() if final_subs.is_dir() else None


def copy_nfo_files_for_seasons(
    nfo_source: Path,
    output_dir: Path,
    seasons: list[int],
    dry_run: bool = False,
) -> None:
    """Copy .nfo files from the submodule into the output dir for the given seasons.
    Copies both episode NFOs and season.nfo. Creates season dirs as needed.
    Copy is done even in dry_run so that the subsequent plan shows proper episode names.
    """
    for season in seasons:
        src_season = nfo_source / f"Season {season}"
        if not src_season.is_dir():
            continue
        dst_season = output_dir / f"Season {season}"
        dst_season.mkdir(parents=True, exist_ok=True)
        for nfo in src_season.glob("*.nfo"):
            shutil.copy2(nfo, dst_season / nfo.name)


def get_plex_name(season_dir: Path, episode_num: int) -> Optional[str]:
    """Read NFO files to find the Plex episode name for a given episode number."""
    pattern = re.compile(rf'S{season_dir.name.replace("Season ", "").zfill(2)}E{episode_num:02d}')
    for nfo in sorted(season_dir.glob("*.nfo")):
        if pattern.search(nfo.stem):
            return nfo.stem  # e.g., "One Pace - S15E01 - Why the Log Pose Is Spherical"
    return None


# ---------------------------------------------------------------------------
# Font attachment (for ASS styling; matches SubKt attach layout)
# Paths relative to subtitle repo main/ (same as sub.properties).
# "min" = common + OP + ED only (~5.5 MB). "full" = also Episode Fonts (~37 MB total).
# ---------------------------------------------------------------------------

FONT_DIRS_MIN = ("Other/Common Fonts", "Other/Opening/Opening Fonts", "Other/Ending/Ending Fonts")
FONT_DIR_EPISODE = "Other/Episode Fonts"  # large (~29 MB); only included when attach_fonts="full"
# Subtitle language key -> extra font dir (relative to main/)
SUBTITLE_LANG_FONT_DIR = {
    "de": "Other/German Fonts", "deu": "Other/German Fonts", "deutsch": "Other/German Fonts", "ger": "Other/German Fonts",
    "es": "Other/Spanish Fonts", "spa": "Other/Spanish Fonts", "spanish": "Other/Spanish Fonts",
    "ar": "Other/Arabic Fonts", "ara": "Other/Arabic Fonts", "arabic": "Other/Arabic Fonts",
    "pl": "Other/Polish Fonts",
    "ru": "Other/Russian Fonts", "rus": "Other/Russian Fonts", "russian": "Other/Russian Fonts",
    "he": "Other/Hebrew Fonts",
}


def collect_font_files(subs_main_dir: Path, subtitle_lang: str, full_fonts: bool = False) -> list[Path]:  # noqa: C901
    """Collect .ttf and .otf from repo font dirs.
    full_fonts=False uses min set (~5.5 MB); True adds Episode Fonts (~37 MB). Deduplicated by path.
    """
    seen: set[Path] = set()
    out: list[Path] = []
    dirs: list[str] = [*FONT_DIRS_MIN]
    if full_fonts:
        dirs.append(FONT_DIR_EPISODE)
    for rel in dirs:
        d = subs_main_dir / rel
        if not d.is_dir():
            continue
        for ext in ("*.ttf", "*.otf"):
            for f in d.glob(ext):
                r = f.resolve()
                if r not in seen:
                    seen.add(r)
                    out.append(f)
    extra = SUBTITLE_LANG_FONT_DIR.get(subtitle_lang.strip().lower())
    if extra:
        d = subs_main_dir / extra
        if d.is_dir():
            for ext in ("*.ttf", "*.otf"):
                for f in d.glob(ext):
                    r = f.resolve()
                    if r not in seen:
                        seen.add(r)
                        out.append(f)
    return sorted(out, key=lambda p: p.name)


def attach_fonts_to_mkv(mkv_path: Path, font_files: list[Path], dry_run: bool = False) -> bool:
    """Append font attachments to MKV using mkvmerge (MKVToolNix). Overwrites mkv_path in place."""
    if not font_files:
        return True
    mkvmerge = shutil.which("mkvmerge")
    if not mkvmerge:
        log.warning("    mkvmerge not found (MKVToolNix); skipping font attachment.")
        return True
    out_temp = mkv_path.with_suffix(".mkv.fonts_tmp")
    # MIME: TTF = font/ttf or application/x-truetype-font, OTF = font/otf
    args = [mkvmerge, "-q", "-o", str(out_temp), str(mkv_path)]
    for f in font_files:
        mime = "application/x-truetype-font" if f.suffix.lower() == ".ttf" else "font/otf"
        args += ["--attachment-mime-type", mime, "--attach-file", str(f)]
    if dry_run:
        log.info("    [dry-run] Would attach %d font(s) with mkvmerge", len(font_files))
        return True
    log.info("    Attaching %d font(s)...", len(font_files))
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("    mkvmerge failed:\n%s", result.stderr)
        return False
    try:
        out_temp.replace(mkv_path)
    except OSError as e:
        log.error("    Could not replace MKV with font-attached version: %s", e)
        return False
    return True


# ---------------------------------------------------------------------------
# Muxing
# ---------------------------------------------------------------------------

def mux_episode(  # noqa: C901
    sub_file: Path,
    dub_file: Optional[Path],
    ass_file: Optional[Path],
    output_file: Path,
    dry_run: bool = False,
    subtitle_lang: str = "eng",
) -> bool:
    """Mux video + audio + subtitles into final MKV.

    When dub is available:
      - Video from dub (clean, no burned subs)
      - Japanese audio from sub, English audio from dub
      - ASS subtitles (language from subtitle_lang)

    When dub is not available:
      - Video + audio from sub
      - ASS subtitles
    """
    sub_iso, sub_title = SUBTITLE_LANG_META.get(subtitle_lang.strip().lower(), ("eng", "English"))
    # Container title for players/Plex (matches SubKt convention: title on mux)
    container_title = output_file.stem  # e.g. "One Pace - S15E01 - Why the Log Pose Is Spherical"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-stats"]

    if dub_file:
        # Input 0: dub (English audio; video only when we have ASS so we use clean dub video)
        # Input 1: sub (video + Japanese audio; when no ASS, sub video may have burned-in EN subs)
        cmd += ["-i", str(dub_file), "-i", str(sub_file)]
        if ass_file:
            cmd += ["-i", str(ass_file)]

        if ass_file:
            cmd += [
                "-map", "0:v:0",     # video from dub (clean)
                "-map", "1:a:0",     # Japanese audio from sub
                "-map", "0:a:0",     # English audio from dub
            ]
        else:
            # No ASS: use sub's video (may have burned-in EN subs, e.g. Buggy's Crew, Koby-Meppo)
            cmd += [
                "-map", "1:v:0",     # video from sub (burned-in subs if present)
                "-map", "1:a:0",     # Japanese audio from sub
                "-map", "0:a:0",     # English audio from dub
            ]
        if ass_file:
            cmd += ["-map", "2:0"]  # subtitle from ASS file

        cmd += [
            "-c:v", "copy",
            "-c:a:0", "ac3", "-b:a:0", AC3_BITRATE,
            "-c:a:1", "ac3", "-b:a:1", AC3_BITRATE,
        ]
        if ass_file:
            cmd += ["-c:s", "copy"]

        cmd += [
            "-metadata:s:a:0", "language=jpn",
            "-metadata:s:a:0", "title=Japanese",
            "-metadata:s:a:1", "language=eng",
            "-metadata:s:a:1", "title=English",
            "-disposition:a:0", "default",
            "-disposition:a:1", "0",
        ]
        if ass_file:
            cmd += [
                "-metadata:s:s:0", f"language={sub_iso}",
                "-metadata:s:s:0", f"title={sub_title}",
                "-disposition:s:0", "default",
            ]
    else:
        # Sub only
        cmd += ["-i", str(sub_file)]
        if ass_file:
            cmd += ["-i", str(ass_file)]

        cmd += [
            "-map", "0:v:0",
            "-map", "0:a:0",
        ]
        if ass_file:
            cmd += ["-map", "1:0"]

        cmd += [
            "-c:v", "copy",
            "-c:a:0", "ac3", "-b:a:0", AC3_BITRATE,
        ]
        if ass_file:
            cmd += ["-c:s", "copy"]

        cmd += [
            "-metadata:s:a:0", "language=jpn",
            "-metadata:s:a:0", "title=Japanese",
            "-disposition:a:0", "default",
        ]
        if ass_file:
            cmd += [
                "-metadata:s:s:0", f"language={sub_iso}",
                "-metadata:s:s:0", f"title={sub_title}",
                "-disposition:s:0", "default",
            ]

    cmd += ["-metadata", f"title={container_title}", str(output_file)]

    if dry_run:
        log.info("    [dry-run] Would run: %s", " ".join(cmd))
        return True

    log.info("    Muxing to %s...", output_file.name)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("    ffmpeg failed:\n%s", result.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def process_arc(arc: ArcConfig, force: bool = False, dry_run: bool = False,  # noqa: C901
                backup_dir: Optional[Path] = None, subtitle_lang: str = "eng",
                download_delay: float = 0, attach_fonts: bool = True, full_fonts: bool = False):
    """Process a single arc: download, mux, attach fonts (if requested), rename, replace."""
    season_dir = ONEPACE_DIR / f"Season {arc.season}"
    season_dir.mkdir(parents=True, exist_ok=True)

    # Copy NFOs for this season when we start (so names are correct and submodule can be updated between runs)
    nfo_source = get_nfo_source_dir()
    if nfo_source:
        copy_nfo_files_for_seasons(nfo_source, ONEPACE_DIR, [arc.season], dry_run=dry_run)

    log.info("\n%s", "=" * 70)
    log.info("Processing: %s (Season %d)", arc.name, arc.season)
    log.info("%s", "=" * 70)
    _debug("SUBS_FINAL_DIR=%s arc_folder=%r", SUBS_FINAL_DIR, arc.arc_folder)

    # Fetch file lists from Pixeldrain
    log.info("  Querying Pixeldrain for Sub files (list: %s)...", arc.sub_id)
    sub_files = pd_list_files(arc.sub_id)
    log.info("  Found %d Sub episodes", len(sub_files))

    dub_files = []
    if arc.dub_id:
        log.info("  Querying Pixeldrain for Dub files (list: %s)...", arc.dub_id)
        dub_files = pd_list_files(arc.dub_id)
        log.info("  Found %d Dub episodes", len(dub_files))

    dub_by_ep = {f.episode_num: f for f in dub_files}

    success_count = 0
    skip_count = 0
    error_count = 0

    for sub_pf in sub_files:
        ep_num = sub_pf.episode_num
        if ep_num == 0:
            log.warning("  Could not determine episode number for: %s", sub_pf.name)
            error_count += 1
            continue

        plex_name = get_plex_name(season_dir, ep_num)
        if not plex_name:
            log.warning("  No NFO found for S%02dE%02d, using fallback name", arc.season, ep_num)
            plex_name = f"One Pace - S{arc.season:02d}E{ep_num:02d} - {arc.name} {ep_num:02d}"

        output_mkv = season_dir / f"{plex_name}.mkv"

        log.info("\n  Episode %02d: %s", ep_num, plex_name)

        # Check if already done
        if output_mkv.exists() and not force:
            log.info("    [skip] Already exists: %s", output_mkv.name)
            skip_count += 1
            continue

        dub_pf = dub_by_ep.get(ep_num)

        # Find subtitle file
        ass_file = find_sub_file(arc, ep_num, sub_pf.name, subtitle_lang=subtitle_lang)
        if ass_file:
            log.info("    Subtitle: %s", ass_file.name)
        else:
            log.info("    [NOTE] No soft subtitle; using sub file video (may have burned-in EN subs)")
            _debug("pd filename tried: %r", sub_pf.name)

        if dry_run:
            log.info("    [dry-run] Would download Sub: %s (%.1f MB)", sub_pf.name, sub_pf.size / 1024 / 1024)
            if dub_pf:
                log.info("    [dry-run] Would download Dub: %s (%.1f MB)", dub_pf.name, dub_pf.size / 1024 / 1024)
            log.info("    [dry-run] Would mux to: %s", output_mkv.name)
            success_count += 1
            continue

        # Create work directory
        ep_work = WORK_DIR / f"s{arc.season:02d}e{ep_num:02d}"
        ep_work.mkdir(parents=True, exist_ok=True)
        move_succeeded = False

        try:
            # Download sub
            sub_local = ep_work / f"sub_{sub_pf.name}"
            pd_download(sub_pf.file_id, sub_local, sub_pf.size)
            if download_delay > 0:
                time.sleep(download_delay)

            # Download dub
            dub_local = None
            if dub_pf:
                dub_local = ep_work / f"dub_{dub_pf.name}"
                pd_download(dub_pf.file_id, dub_local, dub_pf.size)
                if download_delay > 0:
                    time.sleep(download_delay)

            # Mux (when no ASS, mux_episode uses sub's video so burned-in subs are kept)
            temp_output = ep_work / f"{plex_name}.mkv"
            ok = mux_episode(sub_local, dub_local, ass_file, temp_output, dry_run=False, subtitle_lang=subtitle_lang)
            if not ok:
                error_count += 1
                continue

            # Attach fonts for ASS styling (if we have subtitles and attach_fonts)
            if attach_fonts and ass_file:
                subs_main_dir = SUBS_FINAL_DIR.parent.parent
                font_files = collect_font_files(subs_main_dir, subtitle_lang, full_fonts=full_fonts)
                if font_files:
                    if not attach_fonts_to_mkv(temp_output, font_files, dry_run=False):
                        error_count += 1
                        continue

            # Move to final location
            old_mp4 = season_dir / f"{plex_name}.mp4"

            if backup_dir and old_mp4.exists():
                bk = backup_dir / f"Season {arc.season}"
                bk.mkdir(parents=True, exist_ok=True)
                log.info("    Backing up old file to %s", bk / old_mp4.name)
                shutil.move(str(old_mp4), str(bk / old_mp4.name))
            elif old_mp4.exists():
                log.info("    Removing old file: %s", old_mp4.name)
                old_mp4.unlink()

            log.info("    Moving %s to %s", temp_output.name, season_dir)
            shutil.move(str(temp_output), str(output_mkv))

            out_size = output_mkv.stat().st_size / 1024 / 1024
            log.info("    Done! Final size: %.1f MB", out_size)
            success_count += 1
            move_succeeded = True

        except Exception as e:
            log.error("    %s", e)
            error_count += 1
        finally:
            # Clean up work dir only if move succeeded (otherwise muxed file is only in ep_work)
            if ep_work.exists() and move_succeeded:
                shutil.rmtree(ep_work)
            elif ep_work.exists() and not move_succeeded:
                log.info("    [NOTE] Left work dir %s (move failed; muxed file may be there)", ep_work)

    log.info("\n  Summary for %s: %d success, %d skipped, %d errors",
             arc.name, success_count, skip_count, error_count)
    return error_count == 0

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():  # noqa: C901
    parser = argparse.ArgumentParser(
        description="Download and mux One Pace episodes with dual audio + subtitles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --output-dir /path/to/One Pace --season 15
  %(prog)s --all                    Process all 36 arcs (uses ./One Pace or ONEPACE_DIR)
  %(prog)s --season 4 --dry-run     Preview what would happen for Gaimon
  %(prog)s --list                   Show status of all arcs
        """
    )
    parser.add_argument("--season", type=int, action="append", dest="seasons",
                        help="Season number(s) to process (can repeat)")
    parser.add_argument("--all", action="store_true", help="Process all seasons")
    parser.add_argument("--force", action="store_true", help="Overwrite existing MKV files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="Directory to move old MP4 files to instead of deleting")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="One Pace library root (default: ./One Pace or ONEPACE_DIR env)")
    parser.add_argument("--subtitle-lang", type=str, default="eng",
                        help="Subtitle language: eng, deu, por, ara, ita, fra, spa, tur, rus (default: eng)")
    parser.add_argument("--list", action="store_true", help="List all arcs and their status")
    parser.add_argument("--copy-nfo-only", action="store_true",
                        help="Only copy NFO files from one-pace-for-plex into output dir, then exit (no download/mux). Use after updating submodule to fix missing NFOs.")
    parser.add_argument("--debug", action="store_true", help="Print extra debug (e.g. subtitle lookup strategy, paths)")
    parser.add_argument("--download-delay", type=float, default=0, metavar="SECS",
                        help="Pause SECS between downloads (0=no delay). Spreads load under free-tier 6 GB/24h.")
    parser.add_argument("--no-attach-fonts", action="store_true",
                        help="Do not attach subtitle fonts (smaller files; ASS may not render correctly)")
    parser.add_argument("--full-fonts", action="store_true",
                        help="Attach full font set including Episode Fonts (~37 MB/file). Default: min set (~5.5 MB).")

    args = parser.parse_args()

    global DEBUG
    DEBUG = bool(args.debug)

    logging.basicConfig(
        level=logging.DEBUG if DEBUG else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )

    if args.subtitle_lang and args.subtitle_lang.strip().lower() not in SUBTITLE_LANGS:
        log.error("Unknown subtitle language: %s", args.subtitle_lang)
        log.error("  Supported: eng, deu/de, por/pt, ara/ar, ita/it, fra/fr, spa/es, tur/tr, rus/ru")
        sys.exit(1)

    # Set paths from args and environment
    global ONEPACE_DIR, WORK_DIR, SUBS_REPO_DIR, SUBS_FINAL_DIR, PIXELDRAIN_API_KEY
    ONEPACE_DIR = (args.output_dir or Path(os.environ.get("ONEPACE_DIR", "One Pace"))).expanduser().resolve()
    PIXELDRAIN_API_KEY = (os.environ.get("PIXELDRAIN_API_KEY") or "").strip() or None
    WORK_DIR = Path(os.environ.get("ONEPACE_WORK_DIR", "/tmp/onepace_work")).expanduser().resolve()
    if os.environ.get("ONEPACE_SUBS_DIR"):
        SUBS_REPO_DIR = Path(os.environ.get("ONEPACE_SUBS_DIR")).expanduser().resolve()
    else:
        subs_source = get_subs_source_dir()
        SUBS_REPO_DIR = subs_source if subs_source else Path("/tmp/onepace_subs").expanduser().resolve()
    SUBS_FINAL_DIR = SUBS_REPO_DIR / "main" / "Release" / "Final Subs"

    if args.list:
        log.info("%7s  %-30s  %5s  %5s  %s", "Season", "Arc", "Sub", "Dub", "Status")
        log.info("-" * 75)
        for arc in ARCS:
            season_dir = ONEPACE_DIR / f"Season {arc.season}"
            mkv_count = len(list(season_dir.glob("*.mkv"))) if season_dir.exists() else 0
            mp4_count = len(list(season_dir.glob("*.mp4"))) if season_dir.exists() else 0
            dub_status = arc.dub_res if arc.dub_id else "  -  "
            if mkv_count > 0 and mp4_count == 0:
                status = f"Done ({mkv_count} MKV)"
            elif mkv_count > 0:
                status = f"Partial ({mkv_count} MKV, {mp4_count} MP4)"
            else:
                status = f"Pending ({mp4_count} MP4)"
            log.info("  S%02d    %-30s  %5s  %5s  %s", arc.season, arc.name, arc.sub_res, dub_status, status)
        return

    if args.copy_nfo_only:
        nfo_source = get_nfo_source_dir()
        if not nfo_source:
            log.error("one-pace-for-plex submodule not found. Clone with: git clone --recursive ...")
            sys.exit(1)
        copy_seasons = list(range(1, 37)) if args.all else (args.seasons or list(range(1, 37)))
        for s in copy_seasons:
            if s not in ARC_BY_SEASON:
                log.error("Unknown season: %s", s)
                sys.exit(1)
        log.info("Copying NFO files from one-pace-for-plex into %s (seasons %s)...",
                 ONEPACE_DIR, copy_seasons if len(copy_seasons) <= 5 else f"1-36 ({len(copy_seasons)} seasons)")
        copy_nfo_files_for_seasons(nfo_source, ONEPACE_DIR, copy_seasons, dry_run=False)
        log.info("Done. NFOs copied for %d season(s).", len(copy_seasons))
        return

    if not args.seasons and not args.all:
        parser.print_help()
        sys.exit(1)

    seasons_to_process = list(range(1, 37)) if args.all else (args.seasons or [])

    # Validate
    for s in seasons_to_process:
        if s not in ARC_BY_SEASON:
            log.error("Unknown season: %s", s)
            sys.exit(1)

    # Check required tools (ffmpeg) and optional (mkvmerge); offer to install if missing
    ensure_dependencies(offer_install=True, dry_run=args.dry_run)

    if not get_nfo_source_dir():
        log.info("  [NOTE] one-pace-for-plex submodule not found; episode names will use fallback (e.g. Jaya 01).")
        log.info("         Clone with: git clone --recursive https://github.com/snoopyh42/one-pace-mux.git")

    # Ensure subtitle repo
    ensure_subs_repo()

    if not SUBS_FINAL_DIR.is_dir():
        log.error("Subtitle directory not found: %s", SUBS_FINAL_DIR)
        log.error("  Expected 'main/Release/Final Subs' inside the subtitle repo. Re-clone or fix ONEPACE_SUBS_DIR.")
        sys.exit(1)

    # Ensure work directory (restrict permissions when creating)
    WORK_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

    total_start = time.time()
    results = {}

    for s in seasons_to_process:
        arc = ARC_BY_SEASON[s]
        ok = process_arc(arc, force=args.force, dry_run=args.dry_run,
                         backup_dir=args.backup_dir, subtitle_lang=args.subtitle_lang,
                         download_delay=args.download_delay, attach_fonts=not args.no_attach_fonts,
                         full_fonts=args.full_fonts)
        results[s] = ok

    elapsed = time.time() - total_start
    log.info("\n%s", "=" * 70)
    log.info("All done! Processed %d arc(s) in %.1f minutes.", len(results), elapsed / 60)
    for s, ok in results.items():
        arc = ARC_BY_SEASON[s]
        status = "OK" if ok else "ERRORS"
        log.info("  Season %2d (%s): %s", s, arc.name, status)


if __name__ == "__main__":
    main()
