"""球星 Twitter 账号配置加载。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from utils.exceptions import ConfigurationError

_PLAYERS_JSON = Path(__file__).resolve().parent / "players.json"


@dataclass(frozen=True)
class PlayerConfig:
    """球星配置。"""
    name: str
    handle: str
    team: str = ""


def load_players(path: Path | str | None = None) -> list[PlayerConfig]:
    """从 JSON 文件加载球星列表。"""
    filepath = Path(path) if path else _PLAYERS_JSON
    if not filepath.exists():
        raise ConfigurationError(f"球星配置文件不存在: {filepath}")

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"读取球星配置失败: {exc}") from exc

    if not isinstance(data, list):
        raise ConfigurationError("球星配置格式错误: 顶层必须是数组")

    players: list[PlayerConfig] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ConfigurationError(f"球星配置第 {i} 项格式错误: 必须是对象")
        name = item.get("name", "").strip()
        handle = item.get("handle", "").strip()
        if not name or not handle:
            raise ConfigurationError(f"球星配置第 {i} 项缺少 name 或 handle")
        players.append(PlayerConfig(
            name=name,
            handle=handle,
            team=item.get("team", "").strip(),
        ))

    return players


def get_player_by_handle(handle: str, players: list[PlayerConfig] | None = None) -> PlayerConfig | None:
    """按 handle 查找球星。"""
    if players is None:
        players = load_players()
    for p in players:
        if p.handle.lower() == handle.lower():
            return p
    return None
