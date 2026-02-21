"""Tests for onepace_mux.py."""

from pathlib import Path

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
