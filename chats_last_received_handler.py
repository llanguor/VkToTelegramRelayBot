
from json_io import save_data, load_data

FILE = "chats_last_received.json"

def get_last_received_message_id(chat_id):
    chat_id = str(chat_id)
    return data.get(chat_id, -1)

def set_last_received_message_id(chat_id, message_id):
    chat_id = str(chat_id)
    message_id = int(message_id)

    global data
    data[chat_id] = message_id
    save_data(FILE, data)

data = load_data(FILE)