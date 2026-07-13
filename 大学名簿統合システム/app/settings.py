import json
from pathlib import Path


SETTINGS_FILE = Path("settings.json")


DEFAULT_SETTINGS = {
    "last_input_folder": "",
    "last_output_file": "",
    "overwrite": True,
    "save_log": True,
}


class SettingsManager:
    @staticmethod
    def load():
        if not SETTINGS_FILE.exists():
            return DEFAULT_SETTINGS.copy()

        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            settings = DEFAULT_SETTINGS.copy()
            settings.update(data)
            return settings

        except Exception:
            return DEFAULT_SETTINGS.copy()

    @staticmethod
    def save(settings):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)