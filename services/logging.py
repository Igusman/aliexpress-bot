import csv
from pathlib import Path

SEARCH_LOG_FILE = "search_log.txt"

def log_search(original_text: str, translated_text: str):
    search_file = Path(SEARCH_LOG_FILE)
    lines = []

    if search_file.exists():
        with open(search_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="|")
            lines = [line for line in reader]

    normalized = translated_text.strip().lower()
    for idx, line in enumerate(lines):
        if len(line) == 3 and line[1].strip().lower() == normalized:
            lines[idx][2] = str(int(lines[idx][2]) + 1)
            break
    else:
        lines.append([original_text, translated_text, "1"])

    with open(search_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerows(lines)
