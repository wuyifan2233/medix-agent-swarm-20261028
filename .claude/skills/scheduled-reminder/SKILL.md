---
name: scheduled-reminder
description: 设置、查看、修改或取消用药、就诊、复诊提醒。只有用户明确要求提醒、叫我、挂号或复诊时间时才调用。普通用药科普不要调用。不能传入或修改 user_id 和 session_id。
parameters:
  - name: action
    type: string
    required: true
    enum: [create, list, update, cancel]
    description: create 创建，list 查看当前用户的提醒，update 修改，cancel 取消。
  - name: kind
    type: string
    required: false
    enum: [medication, visit, followup]
    description: medication 用药，visit 就诊，followup 复诊。创建时必填。
  - name: repeat
    type: string
    required: false
    enum: [once, daily, weekly]
    description: once 一次，daily 每天，weekly 每周。就诊和复诊没说明时按 once。
  - name: fire_at
    type: string
    required: false
    description: 一次性提醒的绝对时间，使用 Asia/Shanghai，例如 2026-11-04T09:30:00+08:00。必须是未来时间。
  - name: times
    type: string
    required: false
    description: 每天或每周的钟点，多个钟点写成 08:00,20:00，仍然是同一条提醒。不要把「早晚」擅自写成 08:00 和 20:00。
  - name: weekdays
    type: string
    required: false
    description: 每周提醒的星期，例如 周三 或 周一,周四。
  - name: drug
    type: string
    required: false
    description: 用户已经说出的药名。用药提醒必填。不要编造药名。
  - name: dose
    type: string
    required: false
    description: 用户已经说出的剂量。没说就留空，不要编造。
  - name: location
    type: string
    required: false
    description: 用户已经说出的地点或科室。没说就留空，不要编造。
  - name: note
    type: string
    required: false
    description: 用户原话里补充的说明。不要把提醒写成处方。
  - name: reminder_id
    type: string
    required: false
    description: 修改或取消时使用 list 或创建结果返回的 reminder_id。
---

# 定时提醒

把用户说的吃药、就诊、复诊或「到点叫我」记成一条提醒。普通用药科普、症状分析不要调用这个工具。

## 何时调用

- 用户明确说「提醒我」「叫我」「几点吃药」「挂号」「复诊时间」时调用。
- 查看用 `action=list`。改期和取消必须带已经返回的 `reminder_id`。
- 胸痛、呼吸困难、大出血等情况不要创建提醒，直接建议立即就医。

## 怎么填参数

- 先用系统消息里的 Asia/Shanghai 当前时间，把「两小时后」「明天上午」「下周三」算成绝对时间。工具会拒绝不是未来的时间。
- 「早晚」要追问具体钟点，不能写成 08:00 和 20:00。
- 每天多个钟点放在同一个 `times` 里，共用一个 `reminder_id`。
- 就诊、复诊默认 `once`。没说年份时用即将到来的那一天，并在确认里写出完整日期。
- 药名没说、时间不完整，或「有空再去」这类说法，先根据工具返回的问题追问。此时不要说已经设好。
- 剂量和地点只填写用户说过的内容。

## 怎么回复

工具返回 `success=true` 之后，用返回的 `next_fire_at` 和 `canonical_text` 回复，不要改时间或剂量。没拿到成功结果之前，不能说提醒已经设好。

身份由服务端注入。不要传入或改写 `user_id`、`session_id`。
