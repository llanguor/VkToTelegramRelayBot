import json
import logging
import threading
import sys

lock = threading.Lock()

def load_data(filename):
    with lock:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

def save_data(filename, data):
    with lock:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)