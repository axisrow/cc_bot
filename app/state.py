"""Хранение состояния: что уже отправили, чтобы не дублировать уведомления."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

# Путь к файлу состояния. В контейнере рабочая директория /app, том монтируется в /app/data.
STATE_FILE = "data/state.json"


def empty_state() -> dict[str, Any]:
    """Пустое состояние до первого запуска (initialized отсутствует)."""
    return {"incidents": {}, "maintenances": {}, "components": {}}


def load_state(path: str = STATE_FILE) -> dict[str, Any]:
    """Прочитать состояние из JSON. Если файла нет/битый — вернуть пустое."""
    if not os.path.exists(path):
        return empty_state()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Не удалось прочитать состояние из %s: %s — начинаю с пустого", path, exc)
        return empty_state()

    # Подстраховка на случай неполного файла: дефолты для отсутствующих ключей
    return empty_state() | data


def save_state(state: dict[str, Any], path: str = STATE_FILE) -> None:
    """Атомарно записать состояние: временный файл -> os.replace."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        # Подчистить временный файл, чтобы не копился мусор
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
