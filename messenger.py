"""Per-account delivery choice and private channel credentials in the shared database."""
import json
import os
import time
from storage.business import connect


def current_channel(user_id=None):
    forced = os.environ.get('MEDIX_CHANNEL')
    if forced in {'wechat','qq'}: return forced
    if not user_id: return 'wechat'
    with connect() as db:
        row = db.execute('SELECT channel FROM channel_preferences WHERE user_id=?',(user_id,)).fetchone()
    return row['channel'] if row else 'wechat'


def set_channel(name,user_id):
    if name not in {'wechat','qq'}: raise ValueError('请选择微信或 QQ。')
    with connect() as db:
        db.execute('INSERT INTO channel_preferences(user_id,channel) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET channel=excluded.channel',(user_id,name))
    return name


def save_channel_state(channel,user_id,payload):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT user_id FROM channel_bindings WHERE channel=?',(channel,)).fetchone()
        if row and row['user_id'] != user_id:
            raise ValueError('本机渠道已由其他账号连接，请先由原账号断开。')
        db.execute('INSERT INTO channel_bindings(channel,user_id,payload,updated_at) VALUES(?,?,?,?) ON CONFLICT(channel) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',(channel,user_id,json.dumps(payload,ensure_ascii=False),time.time()))


def load_channel_state(channel):
    with connect() as db:
        row=db.execute('SELECT c.payload FROM channel_bindings c JOIN users u ON u.id=c.user_id WHERE c.channel=? AND u.is_active=1',(channel,)).fetchone()
    return json.loads(row['payload']) if row else None


def clear_channel_state(channel,user_id):
    if not user_id:return
    with connect() as db:
        db.execute('DELETE FROM channel_bindings WHERE channel=? AND user_id=?',(channel,user_id))
