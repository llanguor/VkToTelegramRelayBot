import glob
import os
import sys
import time
import requests
import json
import vk_api
import telebot
import threading
from loguru import logger
from telebot import types
from telebot.types import InputMediaPhoto, InputMediaDocument

from chats_handler import change_subscription, load_data, save_data, is_channel_exists, is_conversation_id_exists, get_channel_subscribers, get_subscribes_count, get_channel_name_by_source
from chats_last_received_handler import get_last_received_message_id, set_last_received_message_id

logger.configure(handlers=[{
        "sink": sys.stderr,
        "format": "{time:HH:mm:ss} | {function} | <level>{message}</level>"
    },
    {
        "sink": "log.log",
        "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {function} | {message}",
        "rotation": "10 MB",
        "retention": "7 days"
    }]
)

logger.info(f"Program is running")

with open("appsettings.json", "r", encoding="utf-8") as f:
    data = json.load(f)

with open("chats.json", "r", encoding="utf-8") as f:
    chats = json.load(f)

vk_session = vk_api.VkApi(token=data["vk_token"])
vk = vk_session.get_api()
logger.info(f"Successfully login in vk")

tg_session = telebot.TeleBot(data["tg_token"])
logger.info(f"Successfully login in tg")





@tg_session.message_handler(commands=['start'])
def start(message):
    try:
        logger.info(f"User with id {message.chat.id} called /start command")
        show_chats_keyboard(message, "Привет! Я бот для рассылок с ВК. Выберите чат:")

    except Exception as e:
        logger.error(f"Error in the /start function for the user with ID {message.chat.id}: {e}")


@tg_session.message_handler(commands=['subscribe'])
def subscribe(message):
    try:
        logger.info(f"User with id {message.chat.id} called /subscribe command")
        show_chats_keyboard(message, "Выберите чат:")

    except Exception as e:
        logger.error(f"Error in the /subscribe function for the user with ID {message.chat.id}: {e}")


def show_chats_keyboard(message, text):

    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    try:

        for chat_name in chats.keys():
            keyboard.add(types.InlineKeyboardButton(
                text=chat_name,
                callback_data=f"subscribe_{chat_name}"
            ))

        tg_session.send_message(
            message.chat.id,
            text,
            reply_markup=keyboard)

    except:
        tg_session.send_message(
            message.chat.id, "Что-то пошло не так. Обратитесь к администратору бота",
            reply_markup=keyboard)


@tg_session.callback_query_handler(func=lambda call: call.data.startswith("subscribe_"))
def handle_switch(call):
    try:
        channel_name = call.data[len("subscribe_"):]
        output_id = call.message.chat.id
        print(f"Callback received: {output_id} to channel {channel_name}")

        tg_session.answer_callback_query(call.id)
        is_subscrubed = change_subscription(channel_name, output_id)

        if is_subscrubed:
            tg_session.send_message(call.message.chat.id, f"Вы подписались на чат: {channel_name}")
        else:
            tg_session.send_message(call.message.chat.id, f"Вы отписались от чата: {channel_name}")

    except Exception as e:
        logger.error(f"Error in callback handler for user {output_id}: {e}")

def vk_thread():
    while True:

        try:

            vk.account.setOnline()

            conversations = vk.messages.getConversations(
                filter='unread',
                count=10)['items']

            for conv in conversations:

                peer = conv['conversation']['peer']
                conversation_id = peer['id']
                conversation_type = peer['type']

                if not is_conversation_id_exists(conversation_id):
                    continue

                last_received = get_last_received_message_id(conversation_id)
                if last_received == -1:
                    messages = vk.messages.getHistory(peer_id=conversation_id, count=1)['items']
                    set_last_received_message_id(conversation_id, messages[0]['id'])
                else:
                    messages = vk.messages.getHistory(peer_id=conversation_id, count=20)['items']
                    messages = [m for m in messages if m['id'] > last_received]


                for msg in reversed(messages):
                    logger.info(f"Received message {msg['text']}({msg['id']}) from conversation {conversation_id}")
                    vk.messages.markAsRead(messages_ids=[msg['id']], peer_id=conversation_id)

                    try:
                        send_message_to_telegram(conversation_id, conversation_type, msg)
                    finally:
                        set_last_received_message_id(conversation_id, msg['id'])

            time.sleep(1)

        except BaseException as e:
            logger.warning(f"Something wrong: {e}")
            continue

def send_message_to_telegram(conversation_id, conversation_type, msg):

    opened_documents = []
    try:

        subscribers = get_channel_subscribers(conversation_id)
        sender = get_sender(msg)
        text = msg['text']

        if sender is None:
            return

        attachments, media, documents, opened_documents, caption = get_message_attachments(msg)

        for sub in subscribers:

            channel_name = ""
            if conversation_type!="user" and get_subscribes_count(sub)>1:
                channel_name = get_channel_name_by_source(conversation_id) +" | "
            if channel_name is None:
                channel_name = ""

            if text and caption:
                text+="\n"
            text += caption

            text = str(channel_name + sender + ': ' + text)

            if len(media)==0 and len(attachments)==0:
                tg_session.send_message(sub, text)
                text = ""

            if len(media) != 0:
                media[0].caption = text
                tg_session.send_media_group(sub, media=media)
                text = ""

            if len(documents) != 0:
                tg_session.send_media_group(sub, media=documents)

            for attachment in attachments:

                att_type = attachment.get('type')
                att_link = attachment.get('link')

                if att_type == 'doc' or att_type == 'gif' or att_type == 'audio_message':
                    if text!="":
                        tg_session.send_message(sub, text)
                        text = ""
                    tg_session.send_document(sub, att_link)

                elif att_type == 'other':
                    tg_session.send_message(sub, att_link)

                elif att_type == 'video':
                    tg_session.send_message(sub, text+"\nВидео\n" + att_link)
                    text = ""

                elif att_type == 'graffiti':
                    tg_session.send_message(sub, text+"\nГраффити\n " +att_link)
                    text = ""

            logger.info(f"Send message {msg['text']} to {sub}")

    finally:

        for f in opened_documents:
            try:
                f.close()
            except Exception as e:
                logger.error(f"Error closing file {f}: {e}")

        opened_documents.clear()
        remove_download_cache()


def get_sender(msg):
    if int(msg.get('from_id')) < 0:
        return None
    else:
        dn = vk.users.get(user_ids = msg.get('from_id'))
        name = str (dn[0]['first_name'] + ' ' + dn[0]['last_name'])
    return name


def get_message_attachments(msg):
    attachList = []
    media = []
    documents = []
    caption = ""
    opened_documents = []

    attachments = None

    for att in msg['attachments'][0:]:

        attachments = None
        attType = att.get('type')
        attachment = att[attType]

        if attType == 'photo' :
            sizes = attachment.get('sizes', [])
            media.append(InputMediaPhoto(sizes[-1]['url']))
            continue

        elif attType == 'doc':
            docType = attachment.get('type')
            if docType not in [3, 4, 5]:
                attType = 'other'

            if (docType in [1, 2, 5, 6, 7, 8]) and attachment.get('url'):
                file_path = download_file(attachment['url'], attachment['title'])
                if file_path:
                    document = open(file_path, 'rb')
                    opened_documents.append(document)
                    documents.append(InputMediaDocument(document))
                    continue

            attachments = attachment['url']


        elif attType == 'sticker':  # Проверка на стикеры:
            caption = "Стикер"
            break

        elif attType == 'audio':
            caption = "Аудио-файл"

        elif attType == 'audio_message':
            attachments = attachment.get('link_ogg')

        elif attType == 'video':
            ownerId = str(attachment.get('owner_id'))
            videoId = str(attachment.get('id'))
            accesskey = str(attachment.get('access_key'))

            fullURL = str(ownerId + '_' + videoId + '_' + accesskey)
            attachments = vk.video.get(videos=fullURL)['items'][0].get('player')

        elif attType == 'graffiti':
            attType = 'graffiti'
            attachments = attachment.get('url')

        elif attType == 'link':
            attType = 'other'
            attachments = attachment.get('url')

        elif attType == 'wall':
            attType = 'other'
            attachments = 'https://vk.com/wall'
            from_id = str(attachment.get('from_id'))
            post_id = str(attachment.get('id'))
            attachments += from_id + '_' + post_id

        elif attType == 'wall_reply':
            attType = 'other'
            attachments = 'https://vk.com/wall'
            owner_id = str(attachment.get('owner_id'))
            reply_id = str(attachment.get('id'))
            post_id = str(attachment.get('post_id'))
            attachments += owner_id + '_' + post_id
            attachments += '?reply=' + reply_id

        elif attType == 'poll':
            attType = 'other'
            attachments = 'https://vk.com/poll'
            owner_id = str(attachment.get('owner_id'))
            poll_id = str(attachment.get('id'))
            attachments += owner_id + '_' + poll_id

        else:
            attachments = None

        if attachments is not None:
            attachList.append({'type': attType, 'link': attachments})

    return attachList, media, documents, opened_documents, caption


def remove_download_cache():

    logger.info(f"Download cache cleared")
    files = glob.glob(os.path.join("downloads", "*"))
    for f in files:
        try:
            if os.path.isfile(f):
                os.remove(f)
        except Exception as e:
            logger.error(f"Error while delete file {f}: {e}")


def download_file(url, filename=None):


    try:
        logger.info(f"Downloading file {url}")

        save_dir = "downloads"
        os.makedirs(save_dir, exist_ok=True)

        if filename is None:
            filename = url.split("/")[-1].split("?")[0]  # отбрасываем параметры URL

        file_path = os.path.join(save_dir, filename)

        response = requests.get(url, stream=True)
        response.raise_for_status()

        # Сохраняем файл (перезаписываем, если существует)
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)

        logger.info(f"Downloading file is complete")
        return file_path

    except Exception as e:
        logger.error(f"Error while downloading {url}: {e}")
        return None



threading.Thread(target=vk_thread, daemon=True).start()

while True:
    try:
        tg_session.polling(none_stop=True, interval=1)
    except Exception as e:
        logger.error(f"Exception from main tg_session_polling: {e}")

