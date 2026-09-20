import os
import json
import logging
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio

# --- Настройки ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_FILE = "/data/students.json"
PAYMENT_LINK_4 = os.getenv("PAYMENT_LINK_4", "https://pay.example.com/4")
PAYMENT_LINK_8 = os.getenv("PAYMENT_LINK_8", "https://pay.example.com/8")
PAYMENT_LINK_12 = os.getenv("PAYMENT_LINK_12", "https://pay.example.com/12")

PAYMENT_OPTIONS = {
    "4":  ("4 урока",   PAYMENT_LINK_4),
    "8":  ("8 уроков",  PAYMENT_LINK_8),
    "12": ("12 уроков", PAYMENT_LINK_12),
}

GROUPS = {
    "mon_1030": "Понедельник 10:30 мск",
    "tue_1100": "Вторник 11:00 мск",
    "tue_1800": "Вторник 18:00 мск",
    "wed_1300": "Среда 13:00 мск",
    "wed_1730": "Среда 17:30 мск",
    "thu_1030": "Четверг 10:30 мск",
}

REMINDER_DAYS = [3, 6]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# --- База данных ---
def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_student(user_id):
    return load_db().get(str(user_id))

def save_student(user_id, data):
    db = load_db()
    db[str(user_id)] = data
    save_db(db)


# --- Состояния ---
class Register(StatesGroup):
    waiting_name = State()
    waiting_group = State()

class Broadcast(StatesGroup):
    waiting_text = State()

class SetLink(StatesGroup):
    waiting_link = State()

class AfterClass(StatesGroup):
    selecting_students = State()


# --- Утилиты ---
def is_admin(user_id):
    return user_id == ADMIN_ID

def days_since_reminder(student):
    reminded_at = student.get("reminded_at")
    if not reminded_at:
        return None
    try:
        remind_date = datetime.strptime(reminded_at, "%Y-%m-%d").date()
        return (date.today() - remind_date).days
    except:
        return None

def is_paid_after_reminder(student):
    reminded_at = student.get("reminded_at")
    payment_date = student.get("payment_date")
    if not reminded_at or not payment_date:
        return False
    try:
        remind_date = datetime.strptime(reminded_at, "%Y-%m-%d").date()
        paid_date = datetime.strptime(payment_date, "%Y-%m-%d").date()
        return paid_date >= remind_date
    except:
        return False

def get_links_text(student):
    personal = student.get("payment_link")
    if personal:
        return f"🔗 {personal}"
    return (
        f"🔗 [4 занятия]({PAYMENT_LINK_4})\n\n"
        f"🔗 [8 занятий]({PAYMENT_LINK_8})\n\n"
        f"🔗 [12 занятий]({PAYMENT_LINK_12})"
    )

def reminder_text(name, student):
    links = get_links_text(student)
    return (
        f"Добрый день, {name}!😇\n\n"
        f"Пишу вам напомнить, что у вас осталось 1 оплаченное занятие.\n\n"
        f"Ниже вы можете выбрать подходящий абонемент и оплатить. "
        f"Пожалуйста, внесите оплату до следующего занятия.\n\n"
        f"{links}\n\n"
        f"❗После оплаты нажмите на кнопку \"Оплачено\" и выберите количество оплаченных уроков."
    )


# --- Меню ---
def student_menu():
    """Обычное меню без кнопки оплаты"""
    b = InlineKeyboardBuilder()
    b.button(text="Статус занятий", callback_data="my_info")
    b.button(text="Написать Марии", url="https://t.me/maria_polukhina")
    b.adjust(1)
    return b.as_markup()

def payment_menu():
    """Меню с кнопками подтверждения оплаты — приходит вместе с напоминанием"""
    b = InlineKeyboardBuilder()
    b.button(text="Я оплатил(а) 4 урока", callback_data="plan_4")
    b.button(text="Я оплатил(а) 8 уроков", callback_data="plan_8")
    b.button(text="Я оплатил(а) 12 уроков", callback_data="plan_12")
    b.button(text="Статус занятий", callback_data="my_info")
    b.button(text="Написать Марии", url="https://t.me/maria_polukhina")
    b.adjust(1)
    return b.as_markup()

def admin_menu():
    b = InlineKeyboardBuilder()
    b.button(text="👥 Все ученики", callback_data="admin_list")
    b.button(text="📢 Рассылка всем", callback_data="admin_broadcast")
    b.button(text="✏️ После занятия", callback_data="after_class")
    b.button(text="🔗 Изменить ссылку ученика", callback_data="admin_set_link")
    b.button(text="⏸ Пауза / удаление", callback_data="admin_manage")
    b.button(text="♻️ Реактивировать ученика", callback_data="admin_reactivate")
    b.adjust(1)
    return b.as_markup()

def groups_keyboard():
    b = InlineKeyboardBuilder()
    for key, name in GROUPS.items():
        b.button(text=name, callback_data=f"group_{key}")
    b.adjust(1)
    return b.as_markup()


# --- /start ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    if is_admin(user_id):
        await message.answer("Панель управления:", reply_markup=admin_menu())
        return

    student = get_student(user_id)
    if student and student.get("active") and not student.get("paused"):
        dsr = days_since_reminder(student)
        paid = is_paid_after_reminder(student)
        if paid or dsr is None:
            status = "Оплата актуальна 🤓"
        elif dsr <= 3:
            status = f"Ожидаем оплату ({dsr} дн.) 🤓"
        else:
            status = f"Просрочка {dsr} дн. 🤓"
        await message.answer(
            f"Добрый день, {student['name']}!\n\n"
            f"Группа: {GROUPS.get(student['group'], '?')}\n"
            f"Статус: {status}",
            reply_markup=student_menu()
        )
    elif student and student.get("paused"):
        await message.answer(
            "Ваши занятия сейчас на паузе. "
            "Напишите Марии для возобновления 🤓"
        )
    elif student and not student.get("active"):
        await message.answer(
            "Рады видеть вас снова!\n\n"
            "Ваш аккаунт неактивен. Напишите Марии для возобновления занятий 🙏"
        )
    else:
        await message.answer(
            "Добрый день! Напишите, пожалуйста, своё имя и фамилию 🤓"
        )
        await state.set_state(Register.waiting_name)


# --- Регистрация ---
@dp.message(Register.waiting_name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Выберите вашу группу:", reply_markup=groups_keyboard())
    await state.set_state(Register.waiting_group)

@dp.callback_query(Register.waiting_group, F.data.startswith("group_"))
async def reg_group(callback: types.CallbackQuery, state: FSMContext):
    group_key = callback.data.replace("group_", "")
    data = await state.get_data()
    student = {
        "name": data["name"],
        "group": group_key,
        "payment_date": str(date.today()),
        "payment_link": None,
        "reminded_at": None,
        "active": True,
        "paused": False,
        "registered_at": str(date.today())
    }
    save_student(callback.from_user.id, student)
    await state.clear()
    await bot.send_message(
        ADMIN_ID,
        f"Новый ученик:\n"
        f"{data['name']}\n"
        f"{GROUPS[group_key]}\n"
        f"ID: {callback.from_user.id}"
    )
    await callback.message.answer(
        f"Вы зарегистрированы, {data['name']}!\n\n"
        f"Группа: {GROUPS[group_key]}\n\n"
        f"Мария свяжется с вами для подтверждения!",
        reply_markup=student_menu()
    )
    await callback.answer()





# --- Ученик: выбрал план — фиксируем оплату, одно сообщение ---
@dp.callback_query(F.data.startswith("plan_"))
async def select_plan(callback: types.CallbackQuery):
    plan_key = callback.data.replace("plan_", "")
    student = get_student(callback.from_user.id)
    if not student:
        await callback.answer()
        return

    label, _ = PAYMENT_OPTIONS.get(plan_key, ("?", ""))

    student["payment_date"] = str(date.today())
    student["reminded_at"] = None
    student["last_plan"] = label
    save_student(callback.from_user.id, student)

    await bot.send_message(
        ADMIN_ID,
        f"Оплата!\n"
        f"{student['name']} ({GROUPS.get(student['group'], '?')})\n"
        f"Абонемент: {label}\n"
        f"{date.today().strftime('%d.%m.%Y')}"
    )
    await callback.message.answer(
        f"🌸 Спасибо, {student['name']}! Отмечу вашу оплату ({label}).",
        reply_markup=student_menu()
    )
    await callback.answer()


# --- Ученик: статус ---
@dp.callback_query(F.data == "my_info")
async def my_info(callback: types.CallbackQuery):
    student = get_student(callback.from_user.id)
    if not student:
        await callback.message.answer("Вы не зарегистрированы. Напишите /start")
        await callback.answer()
        return
    dsr = days_since_reminder(student)
    paid = is_paid_after_reminder(student)
    if paid or dsr is None:
        status = "Оплата актуальна 🤓"
    elif dsr <= 3:
        status = f"Ожидаем оплату ({dsr} дн.) 🤓"
    else:
        status = f"Просрочка {dsr} дн. 🤓"
    await callback.message.answer(
        f"Ваш статус:\n\n"
        f"{student['name']}\n"
        f"{GROUPS.get(student['group'], '?')}\n"
        f"Статус: {status}",
        reply_markup=student_menu()
    )
    await callback.answer()


# --- ПОСЛЕ ЗАНЯТИЯ ---
@dp.callback_query(F.data == "after_class")
async def after_class_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    b = InlineKeyboardBuilder()
    for key, name in GROUPS.items():
        b.button(text=name, callback_data=f"afterclass_group_{key}")
    b.adjust(1)
    await callback.message.answer("После какого занятия?", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("afterclass_group_"))
async def after_class_group(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    group_key = callback.data.replace("afterclass_group_", "")
    db = load_db()
    students = [(uid, s) for uid, s in db.items()
                if s.get("active") and not s.get("paused") and s.get("group") == group_key]

    if not students:
        await callback.message.answer("В этой группе нет активных учеников.")
        await callback.answer()
        return

    await state.update_data(group=group_key, selected=[], students=students)

    b = InlineKeyboardBuilder()
    for uid, s in students:
        dsr = days_since_reminder(s)
        reminded = f" {dsr}д" if dsr is not None and not is_paid_after_reminder(s) else ""
        b.button(text=f"[ ] {s['name']}{reminded}", callback_data=f"toggle_{uid}")
    b.button(text="Отправить выбранным", callback_data="afterclass_send")
    b.button(text="Отправить всей группе", callback_data="afterclass_send_all")
    b.adjust(1)

    await callback.message.answer(
        f"*{GROUPS[group_key]}*\n\nОтметь кому отправить напоминание об оплате:",
        parse_mode="Markdown",
        reply_markup=b.as_markup()
    )
    await state.set_state(AfterClass.selecting_students)
    await callback.answer()

@dp.callback_query(AfterClass.selecting_students, F.data.startswith("toggle_"))
async def toggle_student(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.data.replace("toggle_", "")
    data = await state.get_data()
    selected = data.get("selected", [])
    students = data.get("students", [])

    if uid in selected:
        selected.remove(uid)
    else:
        selected.append(uid)
    await state.update_data(selected=selected)

    b = InlineKeyboardBuilder()
    for s_uid, s in students:
        check = "[x]" if s_uid in selected else "[ ]"
        dsr = days_since_reminder(s)
        reminded = f" {dsr}д" if dsr is not None and not is_paid_after_reminder(s) else ""
        b.button(text=f"{check} {s['name']}{reminded}", callback_data=f"toggle_{s_uid}")
    b.button(text="Отправить выбранным", callback_data="afterclass_send")
    b.button(text="Отправить всей группе", callback_data="afterclass_send_all")
    b.adjust(1)

    await callback.message.edit_reply_markup(reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(AfterClass.selecting_students, F.data.in_({"afterclass_send", "afterclass_send_all"}))
async def afterclass_send(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    students = data.get("students", [])
    group_key = data.get("group")

    if callback.data == "afterclass_send_all":
        targets = [uid for uid, _ in students]
    else:
        targets = data.get("selected", [])

    if not targets:
        await callback.answer("Никто не выбран!", show_alert=True)
        return

    db = load_db()
    sent = 0
    today_str = str(date.today())
    for uid, s in students:
        if uid not in targets:
            continue
        try:
            await bot.send_message(
                int(uid),
                reminder_text(s['name'], s),
                parse_mode="Markdown",
                reply_markup=payment_menu()
            )
            if uid in db:
                db[uid]["reminded_at"] = today_str
            sent += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"Ошибка отправки {uid}: {e}")

    save_db(db)
    await state.clear()
    await callback.message.answer(
        f"Напоминания отправлены: {sent} чел.\n"
        f"Авто-напоминания придут через +3 и +6 дней если не оплатят.",
        reply_markup=admin_menu()
    )
    await callback.answer()


# --- АДМИН: список учеников ---
@dp.callback_query(F.data == "admin_list")
async def admin_list(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db = load_db()
    if not db:
        await callback.message.answer("Учеников пока нет.")
        await callback.answer()
        return

    text = ""
    for group_key, group_name in GROUPS.items():
        members = [(uid, s) for uid, s in db.items()
                   if s.get("group") == group_key and s.get("active")]
        if not members:
            continue
        text += f"\n*{group_name}*\n"
        for uid, s in members:
            dsr = days_since_reminder(s)
            paid = is_paid_after_reminder(s)
            if paid or dsr is None:
                status = "ок"
            elif dsr <= 3:
                status = f"{dsr}д"
            elif dsr <= 6:
                status = f"{dsr}д!"
            else:
                status = f"{dsr}д!!"
            paused = " (пауза)" if s.get("paused") else ""
            custom = " (своя ссылка)" if s.get("payment_link") else ""
            text += f"• {s['name']} — {status}{paused}{custom}\n"

    await callback.message.answer(text or "Нет учеников.", parse_mode="Markdown", reply_markup=admin_menu())
    await callback.answer()


# --- АДМИН: рассылка ---
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    b = InlineKeyboardBuilder()
    b.button(text="Всем", callback_data="bc_all")
    for key, name in GROUPS.items():
        b.button(text=name, callback_data=f"bc_{key}")
    b.adjust(1)
    await callback.message.answer("Кому отправить?", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("bc_"))
async def broadcast_pick(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    target = callback.data.replace("bc_", "")
    await state.update_data(bc_target=target)
    await callback.message.answer("Напишите текст сообщения:")
    await state.set_state(Broadcast.waiting_text)
    await callback.answer()

@dp.message(Broadcast.waiting_text)
async def do_broadcast(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    target = data.get("bc_target", "all")
    db = load_db()
    sent = failed = 0
    for uid, s in db.items():
        if not s.get("active") or s.get("paused"):
            continue
        if target != "all" and s.get("group") != target:
            continue
        try:
            await bot.send_message(int(uid), message.text)
            sent += 1
            await asyncio.sleep(0.1)
        except:
            failed += 1
    await state.clear()
    await message.answer(f"Отправлено: {sent}, ошибок: {failed}", reply_markup=admin_menu())


# --- АДМИН: персональная ссылка ---
@dp.callback_query(F.data == "admin_set_link")
async def admin_set_link(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    db = load_db()
    b = InlineKeyboardBuilder()
    for uid, s in db.items():
        if s.get("active"):
            custom = " (своя)" if s.get("payment_link") else ""
            b.button(text=f"{s['name']}{custom}", callback_data=f"setlink_{uid}")
    b.adjust(1)
    await callback.message.answer("Выбери ученика:", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("setlink_"))
async def setlink_pick(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    uid = callback.data.replace("setlink_", "")
    db = load_db()
    s = db.get(uid)
    await state.update_data(setlink_uid=uid)
    current = s.get("payment_link") or "стандартная"
    await callback.message.answer(
        f"{s['name']}\nТекущая ссылка: {current}\n\n"
        f"Введи новую ссылку (или «стандартная» чтобы сбросить):"
    )
    await state.set_state(SetLink.waiting_link)
    await callback.answer()

@dp.message(SetLink.waiting_link)
async def setlink_save(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    uid = data.get("setlink_uid")
    db = load_db()
    if uid in db:
        link = None if message.text.strip().lower() == "стандартная" else message.text.strip()
        db[uid]["payment_link"] = link
        save_db(db)
        result = f"установлена: {link}" if link else "сброшена на стандартную"
        await message.answer(f"{db[uid]['name']}: ссылка {result}", reply_markup=admin_menu())
    await state.clear()


# --- АДМИН: управление ---
@dp.callback_query(F.data == "admin_manage")
async def admin_manage(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    b = InlineKeyboardBuilder()
    b.button(text="Пауза / снять паузу", callback_data="manage_pause")
    b.button(text="Сменить группу", callback_data="manage_change_group")
    b.button(text="Удалить ученика", callback_data="manage_remove")
    b.adjust(1)
    await callback.message.answer("Что сделать?", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "manage_pause")
async def manage_pause(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db = load_db()
    b = InlineKeyboardBuilder()
    for uid, s in db.items():
        if s.get("active"):
            icon = "(пауза)" if s.get("paused") else "(активен)"
            b.button(text=f"{s['name']} {icon}", callback_data=f"pause_{uid}")
    b.adjust(1)
    await callback.message.answer("Выбери ученика:", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("pause_"))
async def toggle_pause(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = callback.data.replace("pause_", "")
    db = load_db()
    if uid in db:
        db[uid]["paused"] = not db[uid].get("paused", False)
        status = "на паузе" if db[uid]["paused"] else "активен"
        save_db(db)
        await callback.message.answer(f"{db[uid]['name']}: {status}", reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "manage_remove")
async def manage_remove(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db = load_db()
    b = InlineKeyboardBuilder()
    for uid, s in db.items():
        if s.get("active"):
            b.button(text=f"{s['name']}", callback_data=f"remove_{uid}")
    b.adjust(1)
    await callback.message.answer("Кого удалить?", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("remove_"))
async def do_remove(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = callback.data.replace("remove_", "")
    db = load_db()
    if uid in db:
        name = db[uid]["name"]
        db[uid]["active"] = False
        save_db(db)
        await callback.message.answer(f"{name} удалён(а). Данные сохранены.", reply_markup=admin_menu())
    await callback.answer()


# --- АДМИН: смена группы ---
@dp.callback_query(F.data == "manage_change_group")
async def manage_change_group(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db = load_db()
    b = InlineKeyboardBuilder()
    for uid, s in db.items():
        if s.get("active"):
            group = GROUPS.get(s.get("group", ""), "?")
            b.button(text=f"{s['name']} ({group})", callback_data=f"chgroup_{uid}")
    b.adjust(1)
    await callback.message.answer("Кому сменить группу?", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("chgroup_") & ~F.data.startswith("chgroup_set_"))
async def chgroup_pick(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = callback.data.replace("chgroup_", "").split("|")[0]
    db = load_db()
    s = db.get(uid)
    current = GROUPS.get(s.get("group", ""), "?")
    b = InlineKeyboardBuilder()
    for key, name in GROUPS.items():
        if key != s.get("group"):
            b.button(text=name, callback_data=f"chgroup_set_{uid}|{key}")
    b.adjust(1)
    await callback.message.answer(
        f"{s['name']}\nТекущая группа: *{current}*\n\nВыбери новую группу:",
        parse_mode="Markdown",
        reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("chgroup_set_"))
async def chgroup_set(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.replace("chgroup_set_", "").split("|", 1)
    uid, new_group = parts[0], parts[1]
    db = load_db()
    if uid in db:
        old_group = GROUPS.get(db[uid].get("group", ""), "?")
        db[uid]["group"] = new_group
        save_db(db)
        name = db[uid]["name"]
        new_group_name = GROUPS.get(new_group, "?")
        await callback.message.answer(
            f"{name} переведён(а)!\n{old_group} → {new_group_name}",
            reply_markup=admin_menu()
        )
        try:
            await bot.send_message(
                int(uid),
                f"Мария перевела вас в новую группу:\n{new_group_name}\n\n"
                f"Если есть вопросы — напишите Марии напрямую 🤓",
                reply_markup=student_menu()
            )
        except Exception as e:
            logging.error(f"Не удалось уведомить ученика {uid}: {e}")
    await callback.answer()


# --- АДМИН: реактивация ---
@dp.callback_query(F.data == "admin_reactivate")
async def admin_reactivate(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db = load_db()
    inactive = [(uid, s) for uid, s in db.items() if not s.get("active")]
    if not inactive:
        await callback.message.answer("Нет деактивированных учеников.", reply_markup=admin_menu())
        await callback.answer()
        return
    b = InlineKeyboardBuilder()
    for uid, s in inactive:
        group = GROUPS.get(s.get("group", ""), "?")
        b.button(text=f"{s['name']} ({group})", callback_data=f"reactivate_{uid}")
    b.adjust(1)
    await callback.message.answer("Кого вернуть?", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("reactivate_"))
async def do_reactivate(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = callback.data.replace("reactivate_", "")
    db = load_db()
    if uid in db:
        db[uid]["active"] = True
        db[uid]["paused"] = False
        db[uid]["reminded_at"] = None
        save_db(db)
        name = db[uid]["name"]
        await callback.message.answer(f"{name} реактивирован(а)!", reply_markup=admin_menu())
        try:
            await bot.send_message(
                int(uid),
                "Добро пожаловать обратно! Ваш аккаунт снова активен 🤓",
                reply_markup=student_menu()
            )
        except Exception as e:
            logging.error(f"Не удалось уведомить ученика {uid}: {e}")
    await callback.answer()


# --- /admin ---
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Панель управления:", reply_markup=admin_menu())


# --- Авто-напоминания (день +3 и +6) ---
async def send_reminders():
    while True:
        now = datetime.now()
        next_run = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())

        db = load_db()
        for uid, s in db.items():
            if not s.get("active") or s.get("paused"):
                continue
            if is_paid_after_reminder(s):
                continue
            dsr = days_since_reminder(s)
            if dsr is None or dsr not in REMINDER_DAYS:
                continue
            try:
                if dsr == 3:
                    msg = reminder_text(s['name'], s)
                elif dsr == 6:
                    msg = (
                        reminder_text(s['name'], s) +
                        "\n\nЕсли есть вопросы — напишите Марии напрямую 🤓"
                    )
                else:
                    continue

                await bot.send_message(int(uid), msg, parse_mode="Markdown", reply_markup=payment_menu())
                await asyncio.sleep(0.1)

                if dsr == 6:
                    await bot.send_message(
                        ADMIN_ID,
                        f"{s['name']} ({GROUPS.get(s['group'], '?')}) — 6 дней без оплаты"
                    )
            except Exception as e:
                logging.error(f"Reminder error {uid}: {e}")


# --- Запуск ---
async def on_startup():
    asyncio.create_task(send_reminders())
    logging.info("Бот Марии запущен!")

async def main():
    dp.startup.register(on_startup)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
