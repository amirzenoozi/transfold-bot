import os
import json


def load_all_locales(locales_path: str, supported_langs: list) -> dict:
    """
    Loads JSON files from the locales_path for the specified supported_langs.
    All comments in this code are in English as requested.
    """
    messages = {}

    # Ensure the path is treated correctly regardless of OS
    normalized_path = os.path.normpath(locales_path)

    for lang in supported_langs:
        # Construct the full path to the json file (e.g., locales/en.json)
        file_path = os.path.join(normalized_path, f"{lang}.json")

        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    messages[lang] = json.load(f)
                print(f"✅ Loaded locale: {lang}")
            except Exception as e:
                print(f"❌ Error loading {lang} from {file_path}: {e}")
                messages[lang] = {}  # Fallback to empty dict if file is corrupted
        else:
            print(f"⚠️ Warning: Locale file not found for '{lang}' at {file_path}")
            messages[lang] = {}  # Fallback to empty dict if file is missing

    return messages


def convert_mb_to_bytes(mb: float) -> int:
    return int(mb * 1024 * 1024)