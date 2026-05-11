import json
from datetime import datetime
from pathlib import Path

SEARCH_LOG_FILE = "search.log"

def log_search(original_text: str, translated_text: str, api_data: dict):
    search_file = Path(SEARCH_LOG_FILE)
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "original_query": original_text,
        "translated_query": translated_text,
        "aliexpress_data": api_data,
    }

    with open(search_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False))
        f.write("\n")
