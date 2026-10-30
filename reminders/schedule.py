"""Turn reminder parameters into the next Asia/Shanghai fire time."""
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, Union
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
LATE_AFTER = timedelta(minutes=2)
WEEKDAYS = {
    "1": 1, "一": 1, "周一": 1, "星期一": 1, "礼拜一": 1, "mon": 1, "monday": 1,
    "2": 2, "二": 2, "周二": 2, "星期二": 2, "礼拜二": 2, "tue": 2, "tues": 2, "tuesday": 2,
    "3": 3, "三": 3, "周三": 3, "星期三": 3, "礼拜三": 3, "wed": 3, "wednesday": 3,
    "4": 4, "四": 4, "周四": 4, "星期四": 4, "礼拜四": 4, "thu": 4, "thur": 4, "thurs": 4, "thursday": 4,
    "5": 5, "五": 5, "周五": 5, "星期五": 5, "礼拜五": 5, "fri": 5, "friday": 5,
    "6": 6, "六": 6, "周六": 6, "星期六": 6, "礼拜六": 6, "sat": 6, "saturday": 6,
    "7": 7, "0": 7, "日": 7, "天": 7, "周日": 7, "周天": 7, "星期日": 7, "星期天": 7,
    "礼拜日": 7, "礼拜天": 7, "sun": 7, "sunday": 7,
}
EMERGENCY_TERMS = ("胸痛", "胸口痛", "呼吸困难", "喘不上气", "大出血", "流血不止", "吐血", "咯血", "呕血")
VAGUE_TERMS = ("有空", "回头", "改天", "随时", "尽快", "有时间", "方便的时候", "方便时", "再说", "晚点再说")
KIND_LABELS = {"medication": "用药提醒", "visit": "就诊提醒", "followup": "复诊提醒"}


@dataclass
class Clarification:
    question: str


def now_shanghai(moment=None):
    current = moment or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def display_local(moment):
    return now_shanghai(moment).strftime("%Y-%m-%d %H:%M")


def iso_local(moment):
    return now_shanghai(moment).replace(microsecond=0).isoformat()


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def asks_emergency(*parts):
    text = "\n".join(clean_text(part) for part in parts)
    return any(term in text for term in EMERGENCY_TERMS)


def _vague(text):
    return any(term in text for term in VAGUE_TERMS)


def _dayparts_without_clock(text):
    return "早晚" in text and not re.search(r"\d", text)


def parse_clock(token):
    text = clean_text(token).lower().replace("：", ":")
    if not text:
        return None
    daypart = None
    for name in ("上午", "早上", "下午", "晚上", "中午"):
        if name in text:
            daypart = name
            text = text.replace(name, "")
    text = text.replace("时", ":").replace("点", ":").replace("分", "").replace(" ", "")
    text = text.strip(":")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{1,2}))?", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if daypart in {"下午", "晚上"} and hour < 12:
        hour += 12
    if daypart == "中午" and hour < 11:
        hour += 12
    if daypart in {"上午", "早上"} and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def parse_times(value) -> Union[list, Clarification]:
    raw = clean_text(value)
    if not raw:
        return Clarification("请补充具体钟点，例如 08:00 或 08:00,20:00。")
    if _vague(raw):
        return Clarification("「有空再去」这类说法还不能设提醒。请给出未来的具体日期和钟点。")
    if _dayparts_without_clock(raw) or any(part in raw and not re.search(r"\d", raw) for part in ("早上", "晚上", "上午", "下午")):
        return Clarification("「早晚」需要具体钟点。请告诉我早上几点、晚上几点，我不会自行写成 08:00 和 20:00。")
    parts = re.split(r"[,，、;；]|(?:\s*(?:和|与|及)\s+)", raw)
    clocks = []
    for part in parts:
        if not clean_text(part):
            continue
        clock = parse_clock(part)
        if clock is None:
            if any(word in part for word in ("早", "晚", "上午", "下午", "中午")) and not re.search(r"\d", part):
                return Clarification("「早晚」需要具体钟点。请告诉我早上几点、晚上几点，我不会自行写成 08:00 和 20:00。")
            return Clarification("有个钟点我没读懂。请用 08:00 这样的时间，多个钟点用逗号分开。")
        clocks.append(clock)
    if not clocks:
        return Clarification("请补充具体钟点，例如 08:00 或 08:00,20:00。")
    return sorted(set(clocks))


def format_times(clocks):
    return ",".join(clock.strftime("%H:%M") for clock in clocks)


def parse_weekdays(value) -> Union[list, Clarification]:
    raw = clean_text(value).lower()
    if not raw:
        return Clarification("每周提醒需要说明是星期几。")
    if _vague(raw):
        return Clarification("「有空再去」这类说法还不能设提醒。请给出未来的具体日期和钟点。")
    tokens = sorted((token for token in WEEKDAYS if token and not token.isdigit()), key=len, reverse=True)
    found = []
    index = 0
    while index < len(raw):
        token = next((item for item in tokens if raw.startswith(item, index)), "")
        if token:
            found.append(WEEKDAYS[token])
            index += len(token)
            continue
        char = raw[index]
        if char.isdigit():
            if char not in WEEKDAYS or (index + 1 < len(raw) and raw[index + 1].isdigit()):
                return Clarification("每周提醒需要说明是星期几，例如周三，或周一和周四。")
            found.append(WEEKDAYS[char])
            index += 1
            continue
        if char not in " ,，、;/和与及的周本下这":
            return Clarification("每周提醒需要说明是星期几，例如周三，或周一和周四。")
        index += 1
    if not found:
        return Clarification("每周提醒需要说明是星期几。")
    return sorted(set(found))


def _clock_from_match(match, groups):
    hour = int(match.group(groups[0]))
    minute = int(match.group(groups[1]) or 0)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _on_date(day, clock):
    return datetime(day.year, day.month, day.day, clock.hour, clock.minute, tzinfo=SHANGHAI)


def _upcoming_month_day(month, day, clock, moment):
    year = moment.year
    for extra in (0, 1):
        try:
            candidate = datetime(year + extra, month, day, clock.hour, clock.minute, tzinfo=SHANGHAI)
        except ValueError:
            return Clarification("这个日期不存在。请换一个具体日期。")
        if candidate > moment:
            return candidate
    return Clarification("这个时间已经过去了。请给一个未来的时间。")


def _weekday_date(moment, iso_day, next_week):
    monday = moment.date() - timedelta(days=moment.isoweekday() - 1)
    weeks = 1 if next_week else 0
    return monday + timedelta(days=weeks * 7 + iso_day - 1)


def parse_fire_at(value, moment) -> Union[datetime, Clarification]:
    raw = clean_text(value)
    moment = now_shanghai(moment)
    if not raw:
        return Clarification("请补充具体的提醒时间，例如明天 08:00。")
    if _vague(raw):
        return Clarification("「有空再去」这类说法还不能设提醒。请给出未来的具体日期和钟点。")
    if _dayparts_without_clock(raw):
        return Clarification("「早晚」需要具体钟点。请告诉我早上几点、晚上几点，我不会自行写成 08:00 和 20:00。")
    relative = re.fullmatch(r"(\d+)\s*(小时|分钟)后", raw)
    if relative:
        amount = int(relative.group(1))
        delta = timedelta(hours=amount) if relative.group(2) == "小时" else timedelta(minutes=amount)
        if amount <= 0:
            return Clarification("请给一个未来的时间。")
        return moment + delta
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        return _future(now_shanghai(parsed), moment)
    named = re.fullmatch(r"(今天|明天|后天)\s*(.+)", raw)
    if named:
        clock = parse_clock(named.group(2))
        if clock is None:
            return Clarification("请补充具体钟点，例如明天 08:00。")
        offset = {"今天": 0, "明天": 1, "后天": 2}[named.group(1)]
        return _future(_on_date(moment.date() + timedelta(days=offset), clock), moment)
    weekly = re.fullmatch(r"(下)?(?:星期|礼拜|周)([一二三四五六日天])\s*(.+)", raw)
    if weekly:
        clock = parse_clock(weekly.group(3))
        if clock is None:
            return Clarification("请补充具体钟点，例如下周三 09:00。")
        day = _weekday_date(moment, WEEKDAYS[weekly.group(2)], bool(weekly.group(1)))
        candidate = _on_date(day, clock)
        if candidate <= moment:
            candidate = _on_date(day + timedelta(days=7), clock)
        return candidate
    month_day = re.fullmatch(r"(\d{1,2})[-/月](\d{1,2})日?\s*(.+)", raw)
    if month_day:
        clock = parse_clock(month_day.group(3))
        if clock is None:
            return Clarification("请补充具体钟点，例如 11月5日 09:30。")
        return _upcoming_month_day(int(month_day.group(1)), int(month_day.group(2)), clock, moment)
    dated = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(.+)", raw)
    if dated:
        clock = parse_clock(dated.group(4))
        if clock is None:
            return Clarification("请补充具体钟点。")
        try:
            candidate = datetime(int(dated.group(1)), int(dated.group(2)), int(dated.group(3)), clock.hour, clock.minute, tzinfo=SHANGHAI)
        except ValueError:
            return Clarification("这个日期不存在。请换一个具体日期。")
        return _future(candidate, moment)
    return Clarification("时间还不完整。请给出未来的具体日期和钟点，例如「明天 08:00」或「2026-11-04 09:30」。")


def _future(candidate, moment):
    if candidate <= moment:
        return Clarification("这个时间已经过去了。请给一个未来的时间。")
    return candidate


def parse_stored_times(schedule):
    clocks = []
    for part in schedule.split(","):
        clock = parse_clock(part)
        if clock is not None:
            clocks.append(clock)
    return clocks


def next_occurrence(repeat, schedule, after):
    """Next slot strictly after `after`. One-shot reminders have no following slot."""
    after = now_shanghai(after)
    if repeat == "once":
        return None
    if repeat == "daily":
        clocks = parse_stored_times(schedule)
        for offset in range(0, 3):
            day = after.date() + timedelta(days=offset)
            for clock in clocks:
                candidate = _on_date(day, clock)
                if candidate > after:
                    return candidate
        return None
    days_text, times_text = schedule.split("@", 1)
    weekdays = {int(item) for item in days_text.split(",") if item}
    clocks = parse_stored_times(times_text)
    for offset in range(0, 15):
        day = after.date() + timedelta(days=offset)
        if day.isoweekday() not in weekdays:
            continue
        for clock in clocks:
            candidate = _on_date(day, clock)
            if candidate > after:
                return candidate
    return None


def canonical_text(kind, when, drug="", dose="", location=""):
    local = display_local(when)
    drug = clean_text(drug)
    dose = clean_text(dose)
    location = clean_text(location)
    if kind == "medication":
        return f"用药提醒：按你设定的时间，现在该服用{drug}{dose}。计划时间 {local}。这是提醒，不是医嘱；如与医生交代不一致，以医嘱为准。"
    if kind == "visit":
        place = location
        return f"就诊提醒：你预约的{place}就诊时间是 {local}。请携带病历和检查资料，提前出发。"
    place = location
    return f"复诊提醒：你设定的复诊时间是 {local}{place}。如需改期，直接告诉我即可。"


def catch_up_text(body, scheduled):
    return body + f"这是补发，只提醒这一次，原定时间 {display_local(scheduled)}。"
