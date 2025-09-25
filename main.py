import glob
import os
import sys
import time
import requests
import json
import vk_api
import telebot
import threading
import re
from PIL.BufrStubImagePlugin import register_handler
from telebot import types
from telebot.types import InputMediaPhoto, InputMediaDocument
from chats_handler import change_subscription, is_conversation_id_exists, get_channel_destinations, get_subscribes_count, get_channel_name_by_source
from chats_last_received_handler import get_last_received_message_id, set_last_received_message_id
from logger import get_logger

id_regex_mask = re.compile(r"\[([A-Za-z0-9]+)\|([^]\s]+)\]")
MARKDOWN_CHARS = ['\\', '_', '*', '[', ']', '(', ')', '~', '`', '>', '<', '&','#', '+', '-', '=', '|', '{', '}', '.', '!']
logger = get_logger()

with open("appsettings.json", "r", encoding="utf-8") as f:
    data = json.load(f)

with open("chats.json", "r", encoding="utf-8") as f:
    chats = json.load(f)

tg_sessions = {}
bot_keyboards = {}
vk_session = vk_api.VkApi(token=data["vk_token"])
vk = vk_session.get_api()
logger.info(f"Successfully login in vk")


def register_handlers(bot, botname):

    @bot.message_handler(commands=['start'])
    def start(message):
        try:
            logger.info(f"User with id {message.chat.id} called /start command")
            show_chats_keyboard(message, "Привет! Я бот для рассылок с ВК. Выберите чат для подписки или отписки:")

        except Exception as e:
            logger.error(f"Error in the /start function for the user with ID {message.chat.id}: {e}")


    @bot.message_handler(commands=['subscribe'])
    def subscribe(message):
        try:
            logger.info(f"User with id {message.chat.id} called /subscribe command")
            show_chats_keyboard(message, "Выберите чат для подписки или отписки:")

        except Exception as e:
            logger.error(f"Error in the /subscribe function for the user with ID {message.chat.id}: {e}")


    def show_chats_keyboard(message, text):

        keyboard = types.InlineKeyboardMarkup(row_width=2)
        buttons = []

        try:

            bot.send_message(
                message.chat.id,
                text,
                reply_markup=bot_keyboards[botname], disable_notification=True)

        except:
            bot.send_message(
                message.chat.id, "Что-то пошло не так. Обратитесь к администратору бота",
                reply_markup=keyboard, disable_notification=True)


    @bot.callback_query_handler(func=lambda call: call.data.startswith("subscribe_"))
    def handle_switch(call):
        try:
            channel_name = call.data[len("subscribe_"):]
            output_id = call.message.chat.id

            bot.answer_callback_query(call.id)
            is_subscrubed = change_subscription(channel_name, botname, output_id)

            if is_subscrubed:
                bot.send_message(call.message.chat.id, f"Вы подписались на чат: {channel_name}", disable_notification=True)
            else:
                bot.send_message(call.message.chat.id, f"Вы отписались от чата: {channel_name}", disable_notification=True)

        except Exception as e:
            logger.error(f"Error in callback handler for user {output_id}: {e}")


def vk_thread():


    conversations = vk.messages.getConversations(count=5)['items']
    conversations = [
        conv for conv in conversations
        if is_conversation_id_exists(conv['conversation']['peer']['id'])
    ]

    while True:

        try:
            if data['vk_set_online_status']:
                vk.account.setOnline()

            for conv in conversations:

                peer = conv['conversation']['peer']
                conversation_id = peer['id']
                conversation_type = peer['type']

                last_received = get_last_received_message_id(conversation_id)
                if last_received == -1:
                    messages = vk.messages.getHistory(peer_id=conversation_id, count=1)['items']
                    set_last_received_message_id(conversation_id, messages[0]['id'])
                else:
                    messages = vk.messages.getHistory(peer_id=conversation_id, count=3)['items']
                    if len(messages) == 0 or messages[0]['id'] <= last_received:
                        continue
                    messages = [m for m in messages if m['id'] > last_received]

                for msg in reversed(messages):
                    logger.info(f"Received message {msg['text']}({msg['id']}) from conversation {conversation_id}")

                    try:
                        send_message_to_telegram(conversation_id, conversation_type, msg)
                    finally:
                        if data['mark_messages_as_read']:
                            vk.messages.markAsRead(messages_ids=[msg['id']], peer_id=conversation_id)
                        set_last_received_message_id(conversation_id, msg['id'])

            time.sleep(data["pause_between_message_checks"])

        except BaseException as e:
            logger.warning(f"Something wrong: {e}")
            continue


def escape_markdown(text: str) -> str:
    for char in MARKDOWN_CHARS:
        text = text.replace(char, f'\\{char}')
    return text

def escape_user_id_vk_mask(text):       #[id12134|@user] => @user
    return id_regex_mask.sub(r"\2", text)

def send_message_to_telegram(conversation_id, conversation_type, msg):
    destinations = get_channel_destinations(conversation_id)
    for bot_name, chat_ids in destinations.items():
        bot = tg_sessions.get(bot_name)
        if not bot:
            logger.warning(f"Bot {bot_name} не найден в tg_sessions")
            continue

        send_message_to_bot(bot, bot_name, chat_ids, msg, conversation_type, conversation_id)

def send_message_to_bot(bot, bot_name, subscribers, msg, conversation_type, conversation_id):

    opened_documents = []
    try:

        if msg.get('action'):
            return

        sender = get_sender_name(msg)
        if sender is None:
            return

        text = escape_user_id_vk_mask(msg['text'])

        attachments, media, documents, opened_documents, caption = get_message_attachments(msg)
        if text and caption:
            text += "\n"
        text += caption

        text_caption = sender + ': ' + text
        forward = get_forward_messages_caption(msg)

        for sub in subscribers:
            try:
                text_to_send = text_caption
                forward_to_send = forward

                channel_name = ""
                if data["add_group_name_to_message"] and conversation_type != "user" and get_subscribes_count(bot_name, sub) > 1:
                    channel_name = get_channel_name_by_source(conversation_id) + " | "
                    if channel_name is not None:
                        text_to_send = channel_name + text_to_send


                if (len(text)!=0 and (
                    len(media) == 0 and len(attachments) == 0 or
                    len(media) != 0 and len(attachments) != 0)):

                    if forward_to_send != "":
                        text_to_send = escape_markdown(text_to_send) + "\n" + forward_to_send
                        bot.send_message(sub, text_to_send, parse_mode='MarkdownV2', disable_notification=data['disable_notification'])
                    else:
                        bot.send_message(sub, text_to_send, disable_notification=data['disable_notification'])

                    text_to_send = ""
                    forward_to_send = ""

                if len(media) != 0:
                    media[0].caption = text_to_send
                    bot.send_media_group(sub, media=media, disable_notification=data['disable_notification'])
                    text_to_send = ""

                for attachment in attachments:

                    att_type = attachment.get('type')
                    att_link = attachment.get('link')

                    if att_type == 'doc' or att_type == 'gif' or att_type == 'audio_message':
                        if text_to_send!="":
                            bot.send_message(sub, text_to_send, disable_notification=data['disable_notification'])
                            text_to_send = ""
                        bot.send_document(sub, att_link, disable_notification=data['disable_notification'])

                    elif att_type == 'other':
                        bot.send_message(sub, text_to_send+"\n" + att_link, disable_notification=data['disable_notification'])
                        text_to_send = ""

                    elif att_type == 'video':
                        bot.send_message(sub, text_to_send+"\nВидео\n" + att_link, disable_notification=data['disable_notification'])
                        text_to_send = ""

                    elif att_type == 'graffiti':
                        bot.send_message(sub, text_to_send+"\nГраффити\n " +att_link, disable_notification=data['disable_notification'])
                        text_to_send = ""

                if len(documents) != 0:
                    bot.send_media_group(sub, media=documents, disable_notification=data['disable_notification'])

                if forward_to_send!="":
                    forward_to_send = escape_markdown(channel_name + sender) + ':\n' + forward_to_send
                    bot.send_message(sub, forward_to_send, parse_mode='MarkdownV2', disable_notification=data['disable_notification'])

                logger.info(f"Send message {msg['text']} to {sub} from bot {bot_name}")

            except Exception as ex:
                logger.error(f"Error while sending {msg['text']} to {sub}: {ex}")

    finally:

        for f in opened_documents:
            try:
                f.close()
            except Exception as e:
                logger.error(f"Error closing file {f}: {e}")

        opened_documents.clear()
        remove_download_cache()


def get_forward_messages_caption(msg):
    fwlist = get_forward_messages_list(msg)
    if len(fwlist) == 0:
        return ""

    text = ""
    is_group = True

    for m in fwlist:
        forward_sender = escape_markdown(m['sender'])
        forward_text = escape_markdown(m['text'])
        if forward_text!='':
            is_group = False

        text += f">{forward_sender}: {forward_text}\n\n"

    if is_group:
        text = f">Группа пересланных сообщений\n"

    return text

def get_forward_messages_list(msg):

    fwd_msg = msg.get('fwd_messages')
    fwd_list = []
    for fwd in fwd_msg:
        fwd_list.append(
            {
                'sender': get_sender_name(fwd),
                'text': fwd.get('text')
            }
        )
        #attachments

    reply_message = msg.get('reply_message')
    if reply_message is not None:
        fwd_list.append(
            {
                'sender': get_sender_name_from_id(reply_message['from_id']),
                'text': reply_message['text']
            }
        )

    return fwd_list



def get_sender_name(msg):
    if int(msg.get('from_id')) < 0:
        return None
    else:
        return get_sender_name_from_id(msg.get('from_id'))

def get_sender_name_from_id(id):
    dn = vk.users.get(user_ids = id)
    return str (dn[0]['first_name'] + ' ' + dn[0]['last_name'])


def get_message_attachments(msg):
    attach_list = []
    media = []
    documents = []
    caption = ""
    opened_documents = []

    attachments = None

    for att in msg['attachments'][0:]:

        attachments = None
        att_type = att.get('type')
        attachment = att[att_type]

        if att_type == 'photo' :
            sizes = attachment.get('sizes', [])
            media.append(InputMediaPhoto(sizes[-1]['url']))
            continue

        elif att_type == 'doc':
            doc_type = attachment.get('type')
            if doc_type not in [3, 4, 5]:
                att_type = 'other'

            if (doc_type in [1, 2, 5, 6, 7, 8]) and attachment.get('url'):
                file_path = download_file(attachment['url'], attachment['title'])
                if file_path:
                    document = open(file_path, 'rb')
                    opened_documents.append(document)
                    documents.append(InputMediaDocument(document))
                    continue

            attachments = attachment['url']


        elif att_type == 'sticker':  # Проверка на стикеры:
            caption = "Стикер"
            break

        elif att_type == 'audio':
            caption = "Аудио-файл"

        elif att_type == 'audio_message':
            attachments = attachment.get('link_ogg')

        elif att_type == 'video':
            owner_id = str(attachment.get('owner_id'))
            video_id = str(attachment.get('id'))
            access_key = str(attachment.get('access_key'))

            full_url = str(owner_id + '_' + video_id + '_' + access_key)
            attachments = vk.video.get(videos=full_url)['items'][0].get('player')

        elif att_type == 'graffiti':
            att_type = 'graffiti'
            attachments = attachment.get('url')

        elif att_type == 'link':
            att_type = 'other'
            attachments = attachment.get('url')

        elif att_type == 'wall':
            att_type = 'other'
            attachments = 'https://vk.com/wall'
            from_id = str(attachment.get('from_id'))
            post_id = str(attachment.get('id'))
            attachments += from_id + '_' + post_id

        elif att_type == 'wall_reply':
            att_type = 'other'
            attachments = 'https://vk.com/wall'
            owner_id = str(attachment.get('owner_id'))
            reply_id = str(attachment.get('id'))
            post_id = str(attachment.get('post_id'))
            attachments += owner_id + '_' + post_id
            attachments += '?reply=' + reply_id

        elif att_type == 'poll':
            att_type = 'other'
            attachments = 'https://vk.com/poll'
            owner_id = str(attachment.get('owner_id'))
            poll_id = str(attachment.get('id'))
            attachments += owner_id + '_' + poll_id

        else:
            attachments = None

        if attachments is not None:
            attach_list.append({'type': att_type, 'link': attachments})

    return attach_list, media, documents, opened_documents, caption


def remove_download_cache():

    files = glob.glob(os.path.join("downloads", "*"))
    for f in files:
        try:
            if os.path.isfile(f):
                os.remove(f)
        except Exception as e:
            logger.error(f"Error while delete file {f}: {e}")


def download_file(url, filename=None):


    try:

        save_dir = "downloads"
        os.makedirs(save_dir, exist_ok=True)

        if filename is None:
            filename = url.split("/")[-1].split("?")[0]

        file_path = os.path.join(save_dir, filename)

        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)

        return file_path

    except Exception as e:
        logger.error(f"Error while downloading {url}: {e}")
        return None


def run_polling(bot, name):
    while True:
        try:
            bot.polling(none_stop=True, interval=1)
        except Exception as e:
            logger.error(f"Exception in polling {name}: {e}")



for name, token in data["tg_tokens"].items():

    bot = telebot.TeleBot(token)
    tg_sessions[name] = bot
    register_handlers(bot, name)

    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for chat_name, chat_data in chats.items():
        destinations = chat_data.get("destinations", {})
        if name in destinations:
            keyboard.add(types.InlineKeyboardButton(
                text=chat_name,
                callback_data=f"subscribe_{chat_name}"
            ))
    bot_keyboards[name] = keyboard

    logger.info(f"Successfully login in tg for {name}")


for name, bot in tg_sessions.items():
    threading.Thread(target=run_polling, args=(bot, name), daemon=True).start()

threading.Thread(target=vk_thread, daemon=True).start()

threading.Event().wait()
