import json
import os
import logging

logger = logging.getLogger("baidu2api")

DEFAULT_CONFIG = {
    "api_keys": [],
    "admin_key": "",
    "toolcall_mode": "xml",
    "max_query_length": 0,
}

CONFIG_PATH = os.environ.get("BAIDU2API_CONFIG_PATH", "config.json")


class Config:
    def __init__(self):
        self._data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            self._data.update(user_config)
            logger.info("Config loaded from %s", CONFIG_PATH)
        except FileNotFoundError:
            logger.info("Config file not found, using defaults")
        except Exception as e:
            logger.warning("Failed to load config: %s", e)

    def save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            logger.info("Config saved to %s", CONFIG_PATH)
        except Exception as e:
            logger.error("Failed to save config: %s", e)

    @property
    def api_keys(self) -> list[str]:
        return self._data.get("api_keys", [])

    @api_keys.setter
    def api_keys(self, value: list[str]):
        self._data["api_keys"] = value

    @property
    def admin_key(self) -> str:
        return self._data.get("admin_key", "")

    @admin_key.setter
    def admin_key(self, value: str):
        self._data["admin_key"] = value

    @property
    def toolcall_mode(self) -> str:
        return self._data.get("toolcall_mode", "xml")

    @toolcall_mode.setter
    def toolcall_mode(self, value: str):
        self._data["toolcall_mode"] = value

    @property
    def max_query_length(self) -> int:
        return self._data.get("max_query_length", 0)

    @max_query_length.setter
    def max_query_length(self, value: int):
        self._data["max_query_length"] = value

    def to_dict(self) -> dict:
        return dict(self._data)

    def update(self, data: dict):
        self._data.update(data)
        self.save()


config = Config()
