import threading
from loguru import logger
from json_io import save_data, load_data
from logger import get_logger

FILE = "chats.json"
lock = threading.Lock()

logger = get_logger()


def is_channel_exists(channel_id):
    return channel_id in data

def is_conversation_id_exists(conversation_id):
    for channel in data.values():
        if str(channel.get("source")) == str(conversation_id):
            return True
    return False

def get_channel_subscribers(source_id):
    for channel in data.values():
        if str(channel.get("source")) == str(source_id):
            return channel.get("subscribers", [])
    return []

def change_subscription(channel_id, chat_id):
    chat_id = str(chat_id)

    with lock:

        global data

        if channel_id not in data:
            logger.error(f"User with chat id {chat_id} can't subscribe to {channel_id}: this channel is not exists: {channel_id}")
            raise ValueError(f"This channel is not exists: {channel_id}")

        if chat_id not in data[channel_id]["subscribers"]:
            data[channel_id]["subscribers"].append(chat_id)
            save_data(FILE, data)
            logger.info(f"User with chat id {chat_id} subscribed to {channel_id}")
            return True
        else:
            data[channel_id]["subscribers"].remove(chat_id)
            save_data(FILE, data)
            logger.info(f"User with chat id {chat_id} unsubscribed from {channel_id}")
            return False

def get_subscribes_count(chat_id):
    chat_id = str(chat_id)
    count = 0

    for channel in data.values():
        if chat_id in channel.get("subscribers", []):
            count += 1

    return count

def get_channel_name_by_source(source_id: str):

    for channel_name, channel_data in data.items():
        if str(channel_data.get("source")) == str(source_id):
            return channel_name
    return None

data = load_data(FILE)
