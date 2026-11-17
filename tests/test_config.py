from datetime import date

import pytest

from labor_law_rag.config import ConfigError, load_corpus_config, load_settings, load_topics, require


def test_require_missing_key_names_the_key(tmp_path, monkeypatch):
    monkeypatch.delenv("LAW_OC", raising=False)
    s = load_settings(env_file=tmp_path / "none.env")
    with pytest.raises(ConfigError, match="LAW_OC"):
        require(s, "law_oc")


def test_settings_read_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LAW_OC", raising=False)
    env = tmp_path / ".env"
    env.write_text("LAW_OC=me\n", encoding="utf-8")
    assert require(load_settings(env_file=env), "law_oc") == "me"


def test_corpus_config_loads_repo_file():
    c = load_corpus_config()
    assert c.base_date == date(2026, 11, 17)
    assert any(law.name == "고용보험법" and "제70조" in law.articles for law in c.laws)
    assert any(law.name == "고용보험법 시행령" and law.delegated_from == "고용보험법" for law in c.laws)


def test_topics_load():
    t = load_topics()
    assert "주휴" in t["주휴수당"]
