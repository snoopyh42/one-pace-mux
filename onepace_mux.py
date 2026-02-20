#!/usr/bin/env python3
"""
One Pace Download & Mux Script

Downloads English Sub and English Dub versions from Pixeldrain, fetches official
ASS subtitles from GitHub, and muxes them into optimized MKV files with:
  - H.264 video (stream copy from Dub version for clean video, or Sub if no dub)
  - Japanese AC3 192k audio (from Sub version)
  - English AC3 192k audio (from Dub version, where available)
  - English ASS subtitles (from one-pace-public-subtitles GitHub repo)

Processes one arc (season) at a time, episode by episode, to minimize temp disk usage.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration (overridable via environment or --output-dir)
# ---------------------------------------------------------------------------

# Set in main() from --output-dir and env (ONEPACE_DIR, ONEPACE_WORK_DIR, ONEPACE_SUBS_DIR)
ONEPACE_DIR: Path = Path("One Pace")
WORK_DIR: Path = Path("/tmp/onepace_work")
SUBS_REPO_DIR: Path = Path("/tmp/onepace_subs")
SUBS_FINAL_DIR: Path = Path("/tmp/onepace_subs/main/Release/Final Subs")

SUBS_REPO_URL = "https://github.com/one-pace/one-pace-public-subtitles.git"
PIXELDRAIN_API = "https://pixeldrain.com/api"
AC3_BITRATE = "192k"

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
    ArcConfig("Straw Hat Adventures",25, "cnjWovN9", "Ua5GkcGr", "720p",  "720p",  "24 If You Could Go Anywhere"),
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
# Pixeldrain helpers
# ---------------------------------------------------------------------------

@dataclass
class PdFile:
    file_id: str
    name: str
    size: int
    episode_num: int = 0


def pd_list_files(list_id: str) -> list[PdFile]:
    """Query Pixeldrain API and return file list for a given list ID."""
    url = f"{PIXELDRAIN_API}/list/{list_id}"
    with urllib.request.urlopen(url) as resp:
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
    """Download a file from Pixeldrain with progress display."""
    url = f"{PIXELDRAIN_API}/file/{file_id}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and expected_size > 0 and dest.stat().st_size == expected_size:
        print(f"    [skip] Already downloaded: {dest.name}")
        return dest

    print(f"    Downloading {dest.name} ({expected_size / 1024 / 1024:.1f} MB)...", end="", flush=True)
    start = time.time()

    req = urllib.request.Request(url)
    try:
        resp = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        print(f"\r    [ERROR] Download failed: HTTP {e.code} for {dest.name}")
        raise
    except urllib.error.URLError as e:
        print(f"\r    [ERROR] Download failed: {e.reason} for {dest.name}")
        raise

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
                print(f"\r    Downloading {dest.name} ({expected_size / 1024 / 1024:.1f} MB)... "
                      f"{pct:.0f}% @ {speed:.1f} MB/s", end="", flush=True)
                last_print = now

    elapsed = time.time() - start
    speed = (expected_size or downloaded) / elapsed / 1024 / 1024 if elapsed > 0 else 0
    print(f"\r    Downloaded {dest.name} ({expected_size / 1024 / 1024:.1f} MB) in {elapsed:.0f}s ({speed:.1f} MB/s)")
    return dest

# ---------------------------------------------------------------------------
# Subtitle helpers
# ---------------------------------------------------------------------------

def ensure_subs_repo():
    """Clone or update the subtitle repository."""
    if SUBS_REPO_DIR.exists() and (SUBS_REPO_DIR / ".git").exists():
        print("  Updating subtitle repository...")
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=SUBS_REPO_DIR,
            capture_output=True,
            timeout=60,
            text=True,
        )
        if result.returncode != 0:
            print(f"[ERROR] Subtitle repo update failed (git pull exited {result.returncode}).")
            if result.stderr:
                print(result.stderr.strip())
            print("  Fix the repo (e.g. resolve conflicts) or remove it and re-run so it can clone fresh.")
            sys.exit(1)
        return
    print("  Cloning subtitle repository (one-time)...")
    if SUBS_REPO_DIR.exists():
        shutil.rmtree(SUBS_REPO_DIR)
    subprocess.run(["git", "clone", "--depth", "1", SUBS_REPO_URL, str(SUBS_REPO_DIR)],
                    check=True, timeout=300)
    print("  Subtitle repository ready.")


def find_sub_file(arc: ArcConfig, episode_num: int, pd_filename: str, subtitle_lang: str = "eng") -> Optional[Path]:
    """Find the matching ASS subtitle file for an episode in the requested language.

    Search strategy:
    1. Try matching by Pixeldrain filename pattern in Final Subs
    2. Try matching by arc name + episode number in Final Subs
    3. Fall back to arc folder in repo for per-episode subs
    """
    lang_key = subtitle_lang.strip().lower()
    final_suffix, arc_suffix = SUBTITLE_LANGS.get(lang_key, ("", "en"))
    # English = no suffix in Final Subs; must end with [resolution].ass not *Language.ass
    want_english = final_suffix == ""

    # Extract the common prefix: [One Pace][chapters] ArcName NN
    base_match = re.match(r'(\[One Pace\]\[.*?\]\s+\S+.*?\s+\d+)', pd_filename)

    # Strategy 1: Match by the chapter+arc+number prefix in Final Subs
    if base_match:
        prefix = base_match.group(1)
        for f in SUBS_FINAL_DIR.iterdir():
            if not f.name.endswith(".ass"):
                continue
            if want_english:
                if re.search(r'(Deutsch|Arabic|Italian|Portugues|French|Spanish|Turkish|Russian)\s*\.ass$', f.name, re.IGNORECASE):
                    continue
                if re.search(r'(Deutsch|Arabic|Italian|Portugues|French|Spanish|Turkish|Russian)\s+(Extended|Alternate)', f.name, re.IGNORECASE):
                    continue
            else:
                if not f.name.endswith(final_suffix + ".ass"):
                    continue
                if re.search(r'\s+(Extended|Alternate)\s*\.ass$', f.name, re.IGNORECASE) and final_suffix + " Extended" not in f.name and final_suffix + " Alternate" not in f.name:
                    continue
            if f.name.startswith(prefix):
                return f

    # Strategy 2: Match by arc name pattern + episode number in Final Subs
    arc_name_pattern = arc.name.replace("'", ".")
    for f in sorted(SUBS_FINAL_DIR.iterdir()):
        if not f.name.endswith(".ass"):
            continue
        if want_english:
            if re.search(r'(Deutsch|Arabic|Italian|Portugues|French|Spanish|Turkish|Russian)', f.name, re.IGNORECASE):
                continue
        else:
            if not f.name.endswith(final_suffix + ".ass"):
                continue
        ep_match = re.search(rf'{arc_name_pattern}\s+0*{episode_num}\b', f.name, re.IGNORECASE)
        if ep_match:
            return f

    # Strategy 3: Fall back to arc episode folder (e.g. "14 Skypiea/24/skypiea 24 en.ass")
    if arc.arc_folder:
        arc_dir = SUBS_REPO_DIR / "main" / arc.arc_folder / f"{episode_num:02d}"
        if not arc_dir.exists():
            arc_dir = SUBS_REPO_DIR / "main" / arc.arc_folder / str(episode_num)
        if arc_dir.exists():
            candidates = []
            for f in sorted(arc_dir.iterdir()):
                if not f.name.endswith(f" {arc_suffix}.ass"):
                    continue
                candidates.append(f)
            if candidates:
                non_alt = [f for f in candidates if "alternate" not in f.name.lower()]
                return non_alt[0] if non_alt else candidates[0]

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
# Muxing
# ---------------------------------------------------------------------------

def mux_episode(
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
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-stats"]

    if dub_file:
        # Input 0: dub (video source + English audio)
        # Input 1: sub (Japanese audio source)
        cmd += ["-i", str(dub_file), "-i", str(sub_file)]
        if ass_file:
            cmd += ["-i", str(ass_file)]

        cmd += [
            "-map", "0:v:0",     # video from dub (clean)
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

    cmd += [str(output_file)]

    if dry_run:
        print(f"    [dry-run] Would run: {' '.join(cmd)}")
        return True

    print(f"    Muxing to {output_file.name}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    [ERROR] ffmpeg failed:\n{result.stderr}")
        return False
    return True

# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_arc(arc: ArcConfig, force: bool = False, dry_run: bool = False,
                backup_dir: Optional[Path] = None, subtitle_lang: str = "eng"):
    """Process a single arc: download, mux, rename, replace."""
    season_dir = ONEPACE_DIR / f"Season {arc.season}"
    season_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"Processing: {arc.name} (Season {arc.season})")
    print(f"{'='*70}")

    # Fetch file lists from Pixeldrain
    print(f"  Querying Pixeldrain for Sub files (list: {arc.sub_id})...")
    sub_files = pd_list_files(arc.sub_id)
    print(f"  Found {len(sub_files)} Sub episodes")

    dub_files = []
    if arc.dub_id:
        print(f"  Querying Pixeldrain for Dub files (list: {arc.dub_id})...")
        dub_files = pd_list_files(arc.dub_id)
        print(f"  Found {len(dub_files)} Dub episodes")

    dub_by_ep = {f.episode_num: f for f in dub_files}

    success_count = 0
    skip_count = 0
    error_count = 0

    for sub_pf in sub_files:
        ep_num = sub_pf.episode_num
        if ep_num == 0:
            print(f"  [WARN] Could not determine episode number for: {sub_pf.name}")
            error_count += 1
            continue

        plex_name = get_plex_name(season_dir, ep_num)
        if not plex_name:
            print(f"  [WARN] No NFO found for S{arc.season:02d}E{ep_num:02d}, using fallback name")
            plex_name = f"One Pace - S{arc.season:02d}E{ep_num:02d} - {arc.name} {ep_num:02d}"

        output_mkv = season_dir / f"{plex_name}.mkv"

        print(f"\n  Episode {ep_num:02d}: {plex_name}")

        # Check if already done
        if output_mkv.exists() and not force:
            print(f"    [skip] Already exists: {output_mkv.name}")
            skip_count += 1
            continue

        dub_pf = dub_by_ep.get(ep_num)

        # Find subtitle file
        ass_file = find_sub_file(arc, ep_num, sub_pf.name, subtitle_lang=subtitle_lang)
        if ass_file:
            print(f"    Subtitle: {ass_file.name}")
        else:
            print(f"    [WARN] No subtitle file found for episode {ep_num}")

        if dry_run:
            print(f"    [dry-run] Would download Sub: {sub_pf.name} ({sub_pf.size/1024/1024:.1f} MB)")
            if dub_pf:
                print(f"    [dry-run] Would download Dub: {dub_pf.name} ({dub_pf.size/1024/1024:.1f} MB)")
            print(f"    [dry-run] Would mux to: {output_mkv.name}")
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

            # Download dub
            dub_local = None
            if dub_pf:
                dub_local = ep_work / f"dub_{dub_pf.name}"
                pd_download(dub_pf.file_id, dub_local, dub_pf.size)

            # Mux
            temp_output = ep_work / f"{plex_name}.mkv"
            ok = mux_episode(sub_local, dub_local, ass_file, temp_output, dry_run=False, subtitle_lang=subtitle_lang)
            if not ok:
                error_count += 1
                continue

            # Move to final location
            old_mp4 = season_dir / f"{plex_name}.mp4"

            if backup_dir and old_mp4.exists():
                bk = backup_dir / f"Season {arc.season}"
                bk.mkdir(parents=True, exist_ok=True)
                print(f"    Backing up old file to {bk / old_mp4.name}")
                shutil.move(str(old_mp4), str(bk / old_mp4.name))
            elif old_mp4.exists():
                print(f"    Removing old file: {old_mp4.name}")
                old_mp4.unlink()

            print(f"    Moving {temp_output.name} to {season_dir}")
            shutil.move(str(temp_output), str(output_mkv))

            out_size = output_mkv.stat().st_size / 1024 / 1024
            print(f"    Done! Final size: {out_size:.1f} MB")
            success_count += 1
            move_succeeded = True

        except Exception as e:
            print(f"    [ERROR] {e}")
            error_count += 1
        finally:
            # Clean up work dir only if move succeeded (otherwise muxed file is only in ep_work)
            if ep_work.exists() and move_succeeded:
                shutil.rmtree(ep_work)
            elif ep_work.exists() and not move_succeeded:
                print(f"    [NOTE] Left work dir {ep_work} (move failed; muxed file may be there)")

    print(f"\n  Summary for {arc.name}: {success_count} success, {skip_count} skipped, {error_count} errors")
    return error_count == 0

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
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

    args = parser.parse_args()

    if args.subtitle_lang and args.subtitle_lang.strip().lower() not in SUBTITLE_LANGS:
        print(f"[ERROR] Unknown subtitle language: {args.subtitle_lang}")
        print("  Supported: eng, deu/de, por/pt, ara/ar, ita/it, fra/fr, spa/es, tur/tr, rus/ru")
        sys.exit(1)

    # Set paths from args and environment
    global ONEPACE_DIR, WORK_DIR, SUBS_REPO_DIR, SUBS_FINAL_DIR
    ONEPACE_DIR = (args.output_dir or Path(os.environ.get("ONEPACE_DIR", "One Pace"))).expanduser().resolve()
    WORK_DIR = Path(os.environ.get("ONEPACE_WORK_DIR", "/tmp/onepace_work")).expanduser().resolve()
    if os.environ.get("ONEPACE_SUBS_DIR"):
        SUBS_REPO_DIR = Path(os.environ.get("ONEPACE_SUBS_DIR")).expanduser().resolve()
    else:
        subs_source = get_subs_source_dir()
        SUBS_REPO_DIR = subs_source if subs_source else Path("/tmp/onepace_subs").expanduser().resolve()
    SUBS_FINAL_DIR = SUBS_REPO_DIR / "main" / "Release" / "Final Subs"

    if args.list:
        print(f"{'Season':>7}  {'Arc':<30}  {'Sub':>5}  {'Dub':>5}  {'Status'}")
        print("-" * 75)
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
            print(f"  S{arc.season:02d}    {arc.name:<30}  {arc.sub_res:>5}  {dub_status:>5}  {status}")
        return

    if not args.seasons and not args.all:
        parser.print_help()
        sys.exit(1)

    seasons_to_process = list(range(1, 37)) if args.all else (args.seasons or [])

    # Validate
    for s in seasons_to_process:
        if s not in ARC_BY_SEASON:
            print(f"[ERROR] Unknown season: {s}")
            sys.exit(1)

    # Copy episode NFOs from one-pace-for-plex submodule into output dir (so MKVs get proper names)
    nfo_source = get_nfo_source_dir()
    if nfo_source:
        if not args.dry_run:
            print("  Copying episode NFOs from one-pace-for-plex into output directory...")
        copy_nfo_files_for_seasons(nfo_source, ONEPACE_DIR, seasons_to_process, dry_run=args.dry_run)
    else:
        print("  [NOTE] one-pace-for-plex submodule not found; episode names will use fallback (e.g. Jaya 01).")
        print("         Clone with: git clone --recursive https://github.com/snoopyh42/one-pace-mux.git")

    # Ensure subtitle repo
    ensure_subs_repo()

    if not SUBS_FINAL_DIR.is_dir():
        print(f"[ERROR] Subtitle directory not found: {SUBS_FINAL_DIR}")
        print("  Expected 'main/Release/Final Subs' inside the subtitle repo. Re-clone or fix ONEPACE_SUBS_DIR.")
        sys.exit(1)

    # Ensure work directory
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    total_start = time.time()
    results = {}

    for s in seasons_to_process:
        arc = ARC_BY_SEASON[s]
        ok = process_arc(arc, force=args.force, dry_run=args.dry_run,
                         backup_dir=args.backup_dir, subtitle_lang=args.subtitle_lang)
        results[s] = ok

    elapsed = time.time() - total_start
    print(f"\n{'='*70}")
    print(f"All done! Processed {len(results)} arc(s) in {elapsed/60:.1f} minutes.")
    for s, ok in results.items():
        arc = ARC_BY_SEASON[s]
        status = "OK" if ok else "ERRORS"
        print(f"  Season {s:2d} ({arc.name}): {status}")


if __name__ == "__main__":
    main()
