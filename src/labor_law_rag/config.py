"""설정 로드: .env(비밀값)와 configs/*.yaml(말뭉치 범위 · 주제)."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel


class ConfigError(Exception):
    pass


class Settings(BaseModel):
    law_oc: str | None = None
    data_go_kr_key: str | None = None
    ollama_url: str = "http://localhost:11434"
    data_dir: Path = Path("data")


_ENV_NAMES = {"law_oc": "LAW_OC", "data_go_kr_key": "DATA_GO_KR_KEY", "ollama_url": "OLLAMA_URL"}


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    file_values = dotenv_values(env_file) if env_file and Path(env_file).exists() else {}
    values = {}
    for field, env_name in _ENV_NAMES.items():
        v = os.environ.get(env_name) or file_values.get(env_name)
        if v:
            values[field] = v
    return Settings(**values)


def require(settings: Settings, name: str) -> str:
    value = getattr(settings, name)
    if not value:
        env_name = _ENV_NAMES.get(name, name.upper())
        raise ConfigError(f"{env_name}가 .env에 없습니다. .env.example을 보세요")
    return value


class LawSpec(BaseModel):
    name: str
    kind: Literal["law", "decree", "notice"]
    articles: list[str] | None = None
    delegated_from: str | None = None
    exclude_articles: list[str] = []


class CorpusConfig(BaseModel):
    base_date: date
    seed: int
    laws: list[LawSpec]
    holdout: dict[str, int]
    near_dup_threshold: float | None = None


def _load_yaml(path: Path):
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_corpus_config(path: Path = Path("configs/corpus.yaml")) -> CorpusConfig:
    return CorpusConfig.model_validate(_load_yaml(path))


_EXCLUDE_KEY = "제외어"


def load_topics(path: Path = Path("configs/topics.yaml")) -> dict[str, list[str]]:
    return {str(k): [str(x) for x in v] for k, v in _load_yaml(path).items() if k != _EXCLUDE_KEY}


def load_topic_excludes(path: Path = Path("configs/topics.yaml")) -> list[str]:
    return [str(x) for x in _load_yaml(path).get(_EXCLUDE_KEY, [])]
