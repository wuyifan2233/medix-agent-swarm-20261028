"""DeepSeek's published CNY tariff, selected at request start (Asia/Shanghai)."""
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

# State Council 2026 holiday notice, including the announced holiday breaks.
# https://www.gov.cn/zhengce/content/202511/content_7047090.htm
HOLIDAYS_2026={(month,day) for month,start,end in [(1,1,3),(2,15,23),(4,4,6),(5,1,5),(6,19,21),(9,25,27),(10,1,7)] for day in range(start,end+1)}

def price_for(model, at=None):
    now=(at or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Shanghai'))
    calendars=json.loads(os.environ.get('MEDIX_PRICE_HOLIDAYS','{}'))
    dates=calendars.get(str(now.year))
    holiday=(now.date().isoformat() in dates) if dates is not None else (now.month,now.day) in HOLIDAYS_2026 if now.year==2026 else False
    known_calendar=now.year==2026 or dates is not None
    peak=now.weekday()<5 and not holiday and (9<=now.hour<12 or 14<=now.hour<18)
    # Unknown future calendars use peak as a clearly marked conservative estimate.
    conservative=not known_calendar and now.weekday()<5 and peak
    factor=2 if peak else 1
    default=None
    if model in {'deepseek-flash','deepseek-v4-flash','deepseek-v4-flash-vision-exp'}:
        default={'input':str(factor),'cached_input':str(Decimal('0.02')*factor),'output':str(4*factor),
                 'currency':'CNY','version':'2026-10-31-flash-cny','period':'peak' if peak else 'off_peak',
                 'started_at':now.isoformat(),'calendar_confirmed':not conservative}
    price=json.loads(os.environ.get('MEDIX_TOKEN_PRICES','{}')).get(model,default)
    if price:
        if price.get('currency')!='CNY': raise ValueError('关怀点计费价格必须使用人民币 CNY。')
        for key in ('input','cached_input','output'):
            value=Decimal(str(price[key]))
            if not value.is_finite() or value<0: raise ValueError('价格必须是非负有限数。')
    return price
