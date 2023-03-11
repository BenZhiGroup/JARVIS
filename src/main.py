import openai
from openai import OpenAIError
import pymysql.cursors
from pymysql import Error
import websocket
import json
import time
import threading
import asyncio
from EdgeGPT import Chatbot
import logging
import urllib.request
import datetime
import subprocess
import xml.etree.ElementTree as ET
from requests import post


HEART_BEAT = 5005
RECV_TXT_MSG = 1
RECV_PIC_MSG = 3
RECV_FILE_MSG = 49
USER_LIST = 5000
GET_USER_LIST_SUCCSESS = 5001
GET_USER_LIST_FAIL = 5002
TXT_MSG = 555
PIC_MSG = 500
AT_MSG = 550
CHATROOM_MEMBER = 5010
CHATROOM_MEMBER_NICK = 5020
PERSONAL_info = 6500
DEBUG_SWITCH = 6000
PERSONAL_DETAIL = 6550
DESTROY_ALL = 9999
NICK_DICK = {}
config = {}
printed_file = []

with open('../config.json', encoding='utf-8') as f:
    config = json.load(f)

openai.api_key = config['openai_key']

connection = pymysql.connect(host=config['mysql_host'],
                             port=config['mysql_port'],
                             user=config['mysql_user'],
                             password=config['mysql_pass'],
                             database='openai',
                             cursorclass=pymysql.cursors.DictCursor)

wxid_fail_list = ['newsapp', 'filehelper', 'weixin', 'mphelper', 'fmessage', 'medianote', 'floatbottle']

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def check_mysql_live():
    global connection
    while True:
        try:
            connection.ping()
            logging.info('MySQL connection is still alive')
        except Error:
            logging.info('MySQL connection is lost')
            connection = pymysql.connect(host=config['mysql_host'],
                                         port=config['mysql_port'],
                                         user=config['mysql_user'],
                                         password=config['mysql_pass'],
                                         database='openai',
                                         cursorclass=pymysql.cursors.DictCursor)
        time.sleep(60)  # 间隔一分钟


def get_recent_chat(wxid):
    with connection.cursor() as cursor:
        sql = 'SELECT `ask`, `response` from chat where type = 1 and wxid = %s and' \
              '`create_time` >= DATE_SUB(NOW(), INTERVAL 60 MINUTE) order by `create_time` desc limit 3'
        cursor.execute(sql, [wxid])
        results = cursor.fetchall()
        return results


def add_chat(chat):
    if len(chat['ask']) > 1:
        with connection.cursor() as cursors:
            insert_sql = 'INSERT INTO chat (type, ask, response, wxid, askid) VALUES (%s,%s,%s,%s,%s)'
            cursors.execute(insert_sql, [chat['type'], chat['ask'], chat['response'], chat['wxid'], chat['askid']])
        connection.commit()
    else:
        with connection.cursor() as cursors:
            insert_sql = 'INSERT INTO chat (ask, response, wxid) VALUES (%s,%s,%s)'
            cursors.execute(insert_sql, [chat['ask'], chat['response'], chat['wxid']])
        connection.commit()


def getid():
    req_id = time.strftime("%Y%m%d%H%M%S", time.localtime(time.time()))
    return req_id


def send_chat_nick(roomid, wxid):
    qs = {
      'id': getid(),
      'type': CHATROOM_MEMBER_NICK,
      'roomid': roomid,
      'wxid': wxid,
      'ext': 'null',
      'nickname': 'null',
      'content': 'null',
    }
    s = json.dumps(qs)
    return s


def send_wxuser_list():
    qs = {
      'id': getid(),
      'type': USER_LIST,
      'content': 'user list',
      'wxid': 'null',
    }
    s = json.dumps(qs)
    return s


def send_person_detail(wxid):
    qs = {
      'id': getid(),
      'type': PERSONAL_DETAIL,
      'content': 'null',
      'wxid': wxid,
    }
    s = json.dumps(qs)
    return s


def send_at_meg(content, roomid, atid):
    qs = {
      'id': getid(),
      'type': AT_MSG,
      'roomid': roomid,
      'wxid': atid,
      'content': content,
      'nickname': NICK_DICK[atid],
      'ext': 'null'
    }
    s = json.dumps(qs)
    return s


def send_txt_msg(msg, wxid):
    qs = {
      'id': getid(),
      'type': TXT_MSG,
      'content': msg,  # 文本消息内容
      'roomid': 'null',
      'nickname': 'null',
      'ext': 'null',
      'wxid': wxid  # wxid,
    }
    s = json.dumps(qs)
    return s


def send_pic_msg(location, wxid):
    qs = {
        'id': getid(),
        'type': PIC_MSG,
        'content': location,
        'roomid': 'null',
        'nickname': 'null',
        'ext': 'null',
        'wxid': wxid
    }
    s = json.dumps(qs)
    return s


def on_open(ws):
    check_live_thread = threading.Thread(target=check_mysql_live)
    check_live_thread.start()
    logging.info('启动了')


def handle_recv_msg(j):
    logging.info('收到信息：' + json.dumps(j))
    wxid = j['wxid']
    askid = j['id1']
    if wxid.startswith("gh_"):
        return
    if wxid in wxid_fail_list:
        return
    if wxid == config['my_wxid']:
        return
    content = j['content']
    # 提问类型 1、是问 GPT 2、问 Bing 3、请求生成图片
    ask_type = 1
    # 是否是 BingGPT 的请求
    if content.startswith('#bing'):
        ask_type = 2
        content = content.replace('#bing', '').lstrip().strip()
    # 是否是生成图片的请求
    if content.find('生成一张图片') != -1 or content.find('生成图片') != -1:
        ask_type = 3
        indx1 = content.find('图片') + 2
        content = content[indx1:].lstrip().strip()
    if content.startswith('#homepodask') or content.startswith('#Homepodask') or content.startswith('#Homepod ask') \
            or content.startswith('#homepod ask') and len(askid) == 0:
        ask_type = 5
        content = content.replace('#homepodask', '').lstrip().strip()
        content = content.replace('#Homepodask', '').lstrip().strip()
        content = content.replace('#Homepod ask', '').lstrip().strip()
        content = content.replace('#homepod ask', '').lstrip().strip()
    if content.startswith('#homepod') or content.startswith('#Homepod') and len(askid) == 0:
        ask_type = 4
        content = content.replace('#homepod', '').lstrip().strip()
    if len(content) < 5 and ask_type != 4:
        send_fail_message(wxid, askid, '问题内容太短')
    m = wxid.find('@chatroom')
    if m != -1:
        # 群消息
        n = content.find('@JARVIS')
        if n != -1:
            # 获取提问人的昵称
            ws.send(send_chat_nick(wxid, askid))
            content = content.replace('@JARVIS', '')
    if ask_type == 2:
        asyncio.run(bing_ask(content, wxid, askid))
    elif ask_type == 3:
        arg = (content, wxid, askid)
        my_thread = threading.Thread(target=pic_ask, args=arg)
        my_thread.start()
    elif ask_type == 4:
        homepod_tts_play(wxid, content)
    elif ask_type == 5:
        arg = (wxid, content)
        my_thread = threading.Thread(target=homepod_tts_gpt_ask, args=arg)
        my_thread.start()
    else:
        arg = (content, wxid, askid)
        my_thread = threading.Thread(target=openai_ask, args=arg)
        my_thread.start()


def handle_recv_pic(j):
    logging.info('收到图片信息：' + json.dumps(j))


def handle_recv_file(j):
    wxid = j['content']['id1']
    if wxid.startswith("gh_"):
        return
    if wxid in wxid_fail_list:
        return
    if wxid.find('@chatroom') != -1:
        return
    try:
        global printed_file
        file_name = ''
        file_type = ''
        xml_str = j['content']['content']
        root = ET.fromstring(xml_str)
        for child in root:
            if child.tag == 'appmsg':
                for child_child in child:
                    if child_child.tag == 'title':
                        file_name = child_child.text
                    if child_child.tag == 'appattach':
                        for child_child_child in child_child:
                            if child_child_child.tag == 'fileext':
                                file_type = child_child_child.text
        if file_type == 'pdf':
            logging.info('准备打印 pdf 文件：' + file_name)
            now = datetime.datetime.now()
            year_month = now.strftime("%Y-%m")
            print_name = year_month + '/' + file_name
            if print_name in printed_file:
                send_fail_message(wxid, '', '打印文件名重复，请换个文件名称。')
                return
            printed_file.append(print_name)
            file_path = '/mnt-file/' + year_month + '/' + file_name
            print_cmd = "sshpass -p BZTec123456! ssh root@192.168.100.27 'lp " + file_path + '\''
            i = 0
            while i < 10:
                try:
                    subprocess.check_output(print_cmd, shell=True)
                    send_fail_message(wxid, '', '文件打印成功✌🏻请去本质科技0号🖨取文件。')
                    return
                except subprocess.CalledProcessError as e:
                    time.sleep(1)
                    i = i + 1
                    continue
    except Exception:
        logging.error('打印文件方法报错了')
        send_fail_message(wxid, '', '文件打印失败，请联系彦祖查询原因。')


def handle_nick(j):
    data = json.loads(j['content'])
    nick = data['nick']
    wxid = data['wxid']
    global NICK_DICK
    NICK_DICK[wxid] = nick


def handle_wxuser_list(j):
    j_ary_0 = j['content']
    j_ary = []
    # 去掉微信官方账号
    for item in j_ary_0:
        id = item['wxid']
        if id not in wxid_fail_list:
            j_ary.append(item)
    # 去掉公众号
    for item in j_ary:
        id = item['wxid']
        if id.startswith("gh_"):
            j_ary.remove(item)


def handle_nothing(j):
    print('')


def handle_heart_beat(j):
    logging.info('---心跳检测：正常---')


def openai_ask(ask, wxid, askid):
    chats = get_recent_chat(wxid)
    reversed_chats = []
    for item in chats:
        reversed_chats.insert(0, {'role': 'user', 'content': item['ask']})
        reversed_chats.insert(1, {'role': 'assistant', 'content': item['response']})
    reversed_chats.append({"role": "user", "content": ask})
    try:
        logging.info(wxid + ' 向 OpenAI 发出提问：' + json.dumps(reversed_chats))
        data = openai.ChatCompletion.create(
            model='gpt-3.5-turbo',
            messages=reversed_chats
        )
        response = data['choices'][0]['message']['content'].lstrip().strip()
        logging.info('收到 ' + wxid + ' 提问的 OpenAI 的回复' + response)
        if len(askid) > 0:
            ws.send(send_at_meg(response, wxid, askid))
        else:
            ws.send(send_txt_msg(response, wxid))
        add_chat({'type': 1, 'wxid': wxid, 'askid': askid, 'ask': ask, 'response': response})
    except OpenAIError as openai_error:
        send_fail_message(wxid, askid, '出错了，请联系彦祖。错误信息：' + openai_error)


async def bing_ask(ask, wxid, askid):
    try:
        logging.info(wxid + ' 向 Bing 发出提问：' + ask)
        bot = Chatbot(cookiePath='../cookies.json')
        data = await bot.ask(prompt=ask)
        response = data["item"]["messages"][1]['text'].replace('^', '')
        response = response.replace('你好，这是必应。', '')
        response = response.replace('你好，这是Bing。', '')
        response = response.replace('您好，这是Bing。', '')
        response = response.replace('您好，这是必应。', '')
        response = response.replace('👋', '')
        response = response.replace('😊', '')
        response = response.lstrip().strip()
        logging.info('收到 ' + wxid + ' 提问的 Bing 的回复' + response)
        url_list = data["item"]["messages"][1]['sourceAttributions']
        await bot.close()
        if len(askid) > 0:
            ws.send(send_at_meg(response, wxid, askid))
        else:
            ws.send(send_txt_msg(response, wxid))
        if len(url_list) > 0:
            url_response = '相关链接：\n'
            for inx, item in enumerate(url_list):
                num = inx + 1
                url_response = url_response + '[' + str(num) + '] ' + item['seeMoreUrl'] + '\n'
            if len(askid) > 0:
                ws.send(send_at_meg(url_response, wxid, askid))
            else:
                ws.send(send_txt_msg(url_response, wxid))
            response = response + '\n' + url_response
        add_chat({'type': 2, 'wxid': wxid, 'askid': askid, 'ask': ask, 'response': response})
    except Exception as err:
        print(json.dumps(err))
        send_fail_message(wxid, askid, 'BingChat服务报错了，请5分钟后重试。若连续三次不可用请联系彦祖。')


def pic_ask(ask, wxid, askid):
    try:
        logging.info(wxid + ' 向 OpenAI 发出生成图片请求：' + ask)
        response = openai.Image.create(
            prompt=ask,
            n=1,
            size="1024x1024"
        )
        image_url = response['data'][0]['url']
        add_chat({'type': 3, 'wxid': wxid, 'askid': askid, 'ask': ask, 'response': image_url})
        pic_name = getid() + '.png'
        urllib.request.urlretrieve(image_url, '/mnt/' + pic_name)
        ws.send(send_pic_msg('C:\\Users\\benzhidev\\Desktop\\git\\openai-img\\' + pic_name, wxid))
    except Exception as err:
        print(json.dumps(err))
        send_fail_message(wxid, askid, 'OpenAI 生成图片服务报错了，请5分钟后重试。若连续三次不可用请联系彦祖。')


def homepod_tts_play(wxid, ask):
    request_body = '{"entity_id":"media_player.gong_zuo_shi","language":"zh-CN"}'
    j = json.loads(request_body)
    j['message'] = ask
    url = config['ha-url'] + '/services/tts/google_translate_say'
    headers = {"Authorization": 'Bearer ' + config['ha-token']}
    post(url, headers=headers, json=j)
    send_fail_message(wxid, '', '办公室的 Homepod 播放成功')


def homepod_tts_gpt_ask(wxid, ask):
    chats = get_recent_chat(wxid)
    new_ask = ask + ' 请用50字以内回答。'
    reversed_chats = []
    for item in chats:
        reversed_chats.insert(0, {'role': 'user', 'content': item['ask']})
        reversed_chats.insert(1, {'role': 'assistant', 'content': item['response']})
    reversed_chats.append({"role": "user", "content": new_ask})
    try:
        logging.info(wxid + ' 向 OpenAI 发出提问：' + json.dumps(reversed_chats))
        data = openai.ChatCompletion.create(
            model='gpt-3.5-turbo',
            messages=reversed_chats
        )
        response = data['choices'][0]['message']['content'].lstrip().strip()
        logging.info('收到 ' + wxid + ' 提问的 OpenAI 的回复' + response)
        homepod_tts_play(wxid, response)
    except OpenAIError as openai_error:
        send_fail_message(wxid, '', '出错了，请联系彦祖。错误信息：' + openai_error)


def send_fail_message(wxid, askid, error_str):
    if len(askid) > 0:
        ws.send(send_at_meg(error_str, wxid, askid))
    else:
        ws.send(send_txt_msg(error_str, wxid))


def on_message(ws, message):
    j = json.loads(message)
    resp_type = j['type']
    action = {
      CHATROOM_MEMBER_NICK: handle_nick,
      PERSONAL_DETAIL: handle_nothing,
      AT_MSG: handle_nothing,
      DEBUG_SWITCH: handle_nothing,
      PERSONAL_info: handle_nothing,
      TXT_MSG: handle_nothing,
      PIC_MSG: handle_nothing,
      CHATROOM_MEMBER: handle_nothing,
      RECV_PIC_MSG: handle_recv_pic,
      RECV_TXT_MSG: handle_recv_msg,
      RECV_FILE_MSG: handle_recv_file,
      HEART_BEAT: handle_heart_beat,
      USER_LIST: handle_wxuser_list,
      GET_USER_LIST_SUCCSESS: handle_nothing,
      GET_USER_LIST_FAIL: handle_nothing,
    }
    action.get(resp_type, handle_nothing)(j)


def on_error(ws, error):
    logging.ERROR('error')


def on_close(ws):
    logging.info('closed')


websocket.enableTrace(True)
ws = websocket.WebSocketApp(config['server'],
                            on_open=on_open,
                            on_message=on_message,
                            on_error=on_error,
                            on_close=on_close)
ws.run_forever()
