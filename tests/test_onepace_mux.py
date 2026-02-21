"""Tests for onepace_mux.py."""

from pathlib import Path
from unittest.mock import patch

import onepace_mux as mux


class TestSubtitleLangMaps:
    """SUBTITLE_LANGS and SUBTITLE_LANG_META coverage."""

    def test_english_aliases(self):
        assert mux.SUBTITLE_LANGS["eng"] == ("", "en")
        assert mux.SUBTITLE_LANGS["en"] == ("", "en")
        assert mux.SUBTITLE_LANG_META["eng"] == ("eng", "English")
        assert mux.SUBTITLE_LANG_META["en"] == ("eng", "English")

    def test_german_aliases(self):
        assert mux.SUBTITLE_LANGS["deu"] == (" Deutsch", "de")
        assert mux.SUBTITLE_LANGS["de"] == (" Deutsch", "de")
        assert mux.SUBTITLE_LANG_META["deu"] == ("deu", "German")

    def test_unknown_lang_fallback(self):
        iso, title = mux.SUBTITLE_LANG_META.get("zzz", ("eng", "English"))
        assert iso == "eng" and title == "English"

    def test_all_lang_meta_have_iso_and_title(self):
        for key, (iso, title) in mux.SUBTITLE_LANG_META.items():
            assert len(iso) == 3, f"{key}: bad iso {iso}"
            assert len(title) >= 2, f"{key}: bad title {title}"


class TestArcConfig:
    """ARCS and ARC_BY_SEASON."""

    def test_arc_by_season_covers_1_to_36(self):
        for s in range(1, 37):
            assert s in mux.ARC_BY_SEASON, f"missing season {s}"

    def test_arc_config_has_required_fields(self):
        for arc in mux.ARCS:
            assert arc.season >= 1
            assert arc.name
            assert arc.sub_id
            assert arc.sub_res
            assert arc.dub_res is not None

    def test_arc_by_season_matches_arcs(self):
        for arc in mux.ARCS:
            assert mux.ARC_BY_SEASON[arc.season] is arc


class TestCollectFontFiles:
    """collect_font_files with temp dirs."""

    def test_empty_dir_returns_empty_list(self, tmp_path):
        (tmp_path / "Other" / "Common Fonts").mkdir(parents=True)
        assert mux.collect_font_files(tmp_path, "eng") == []

    def test_collects_ttf_and_otf(self, tmp_path):
        common = tmp_path / "Other" / "Common Fonts"
        common.mkdir(parents=True)
        (common / "a.ttf").write_bytes(b"fake")
        (common / "b.otf").write_bytes(b"fake")
        result = mux.collect_font_files(tmp_path, "eng")
        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"a.ttf", "b.otf"}

    def test_min_excludes_episode_fonts_dir(self, tmp_path):
        (tmp_path / "Other" / "Common Fonts").mkdir(parents=True)
        (tmp_path / "Other" / "Episode Fonts").mkdir(parents=True)
        (tmp_path / "Other" / "Common Fonts" / "x.ttf").write_bytes(b"x")
        (tmp_path / "Other" / "Episode Fonts" / "y.ttf").write_bytes(b"y")
        result_min = mux.collect_font_files(tmp_path, "eng", full_fonts=False)
        result_full = mux.collect_font_files(tmp_path, "eng", full_fonts=True)
        assert len(result_min) == 1
        assert len(result_full) == 2

    def test_lang_specific_font_dir_included(self, tmp_path):
        (tmp_path / "Other" / "Common Fonts").mkdir(parents=True)
        (tmp_path / "Other" / "German Fonts").mkdir(parents=True)
        (tmp_path / "Other" / "Common Fonts" / "c.ttf").write_bytes(b"c")
        (tmp_path / "Other" / "German Fonts" / "g.ttf").write_bytes(b"g")
        result = mux.collect_font_files(tmp_path, "deu")
        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"c.ttf", "g.ttf"}

    def test_deduplicates_by_resolved_path(self, tmp_path):
        common = tmp_path / "Other" / "Common Fonts"
        common.mkdir(parents=True)
        (common / "a.ttf").write_bytes(b"a")
        result = mux.collect_font_files(tmp_path, "eng")
        assert len(result) == 1


class TestAttachFontsToMkv:
    """attach_fonts_to_mkv behavior."""

    def test_empty_font_list_returns_true(self):
        assert mux.attach_fonts_to_mkv(Path("/nonexistent.mkv"), [], dry_run=False) is True

    def test_dry_run_with_fonts_returns_true(self, tmp_path):
        (tmp_path / "f.ttf").write_bytes(b"x")
        assert mux.attach_fonts_to_mkv(
            tmp_path / "out.mkv", [tmp_path / "f.ttf"], dry_run=True
        ) is True


class TestFindSubFile:
    """find_sub_file strategy behavior with temp Final Subs and repo layout."""

    def test_strategy_1_prefix_match(self, tmp_path):
        """Strategy 1: match by Pixeldrain-style prefix in Final Subs."""
        final_subs = tmp_path / "Final Subs"
        final_subs.mkdir(parents=True)
        (final_subs / "[One Pace][96-97] Jaya 01 [1080p].ass").write_text("")
        (final_subs / "[One Pace][96-97] Jaya 01 [1080p] Deutsch.ass").write_text("")
        arc = mux.ARC_BY_SEASON[15]  # Jaya
        with patch.object(mux, "SUBS_FINAL_DIR", final_subs), patch.object(
            mux, "SUBS_REPO_DIR", tmp_path
        ):
            found = mux.find_sub_file(
                arc, 1, "[One Pace][96-97] Jaya 01 [1080p].mp4", subtitle_lang="eng"
            )
        assert found is not None
        assert found.name == "[One Pace][96-97] Jaya 01 [1080p].ass"

    def test_strategy_2_arc_ep_match(self, tmp_path):
        """Strategy 2: match by arc name + episode number."""
        final_subs = tmp_path / "Final Subs"
        final_subs.mkdir(parents=True)
        (final_subs / "[One Pace][98-99] Jaya 02 [1080p].ass").write_text("")
        arc = mux.ARC_BY_SEASON[15]
        with patch.object(mux, "SUBS_FINAL_DIR", final_subs), patch.object(
            mux, "SUBS_REPO_DIR", tmp_path
        ):
            found = mux.find_sub_file(
                arc, 2, "[One Pace][98-99] Jaya 02 [1080p].mp4", subtitle_lang="eng"
            )
        assert found is not None
        assert "02" in found.name and "Jaya" in found.name

    def test_strategy_3_single_arc_file(self, tmp_path):
        """Strategy 3: single file matching arc name (whole-arc sub)."""
        final_subs = tmp_path / "Final Subs"
        final_subs.mkdir(parents=True)
        (final_subs / "[One Pace] Gaimon [1080p].ass").write_text("")
        arc = mux.ARC_BY_SEASON[4]  # Gaimon (single-word arc, no apostrophe/space in name)
        with patch.object(mux, "SUBS_FINAL_DIR", final_subs), patch.object(
            mux, "SUBS_REPO_DIR", tmp_path
        ):
            found = mux.find_sub_file(
                arc, 1, "Some other filename 01 [1080p].mp4", subtitle_lang="eng"
            )
        assert found is not None
        assert "Gaimon" in found.name

    def test_strategy_4_arc_folder_episode_dir(self, tmp_path):
        """Strategy 4: fall back to arc folder / episode number / lang .ass."""
        main_dir = tmp_path / "main"
        (main_dir / "15 Jaya" / "01").mkdir(parents=True)
        (main_dir / "15 Jaya" / "01" / "jaya 01 en.ass").write_text("")
        arc = mux.ARC_BY_SEASON[15]
        with patch.object(mux, "SUBS_FINAL_DIR", tmp_path / "empty"), patch.object(
            mux, "SUBS_REPO_DIR", tmp_path
        ):
            (tmp_path / "empty").mkdir(exist_ok=True)
            found = mux.find_sub_file(arc, 1, "Jaya 01 [1080p].mp4", subtitle_lang="eng")
        assert found is not None
        assert found.name == "jaya 01 en.ass"

    def test_no_match_returns_none(self, tmp_path):
        """When nothing matches, find_sub_file returns None."""
        final_subs = tmp_path / "Final Subs"
        final_subs.mkdir(parents=True)
        arc = mux.ARC_BY_SEASON[1]
        with patch.object(mux, "SUBS_FINAL_DIR", final_subs), patch.object(
            mux, "SUBS_REPO_DIR", tmp_path
        ):
            found = mux.find_sub_file(arc, 99, "Unknown 99 [1080p].mp4", subtitle_lang="eng")
        assert found is None


class TestMuxEpisode:
    """mux_episode behavior."""

    def test_dry_run_returns_true(self, tmp_path):
        """With dry_run=True, mux_episode returns True without running ffmpeg."""
        sub_f = tmp_path / "sub.mp4"
        sub_f.write_bytes(b"fake")
        out_f = tmp_path / "out.mkv"
        assert mux.mux_episode(
            sub_f, None, None, out_f, dry_run=True, subtitle_lang="eng"
        ) is True
        assert not out_f.exists()


class TestPdDownloadCaching:
    """pd_download skips re-download when file exists with correct size."""

    def test_returns_early_when_file_exists_with_matching_size(self, tmp_path):
        """When dest exists and size matches expected_size, no download is attempted."""
        dest = tmp_path / "cached.mp4"
        size = 1024
        dest.write_bytes(b"x" * size)
        with patch.object(mux, "_urlopen_with_retry") as mock_open:
            result = mux.pd_download("dummy_id", dest, expected_size=size)
        assert result == dest
        mock_open.assert_not_called()
