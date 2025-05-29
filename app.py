import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup,ReplyKeyboardMarkup,KeyboardButton
from bot_token import bot_token
TOKEN = bot_token
ADMIN_ID = 868359912
DB_PATH = 'users.db'

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

admin_reply_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📢 Заявить о происшествии")],
        [KeyboardButton(text="➕ Добавить пользователя")],
    ],
    resize_keyboard=True,  # подгоняет по размеру
    one_time_keyboard=False  # клавиатура будет оставаться
)

class NotifyIncident(StatesGroup):
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_segment = State()
    waiting_for_track = State()
    waiting_for_kmpk = State()
    waiting_for_type = State()
    waiting_for_description = State()
    waiting_for_chairman = State()

# --- инициализация БД ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # подписчики
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )""")
        # сохранённые оповещения
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                time TEXT,
                segment TEXT,
                track TEXT,
                km_pk TEXT,
                incident_type TEXT,
                description TEXT,
                chairman TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        await db.commit()

# --- работа с подписчиками ---
async def add_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )
        await db.commit()

async def get_users() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

# --- работа с оповещениями ---
async def add_notification(data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO notifications
            (date, time, segment, track, km_pk, incident_type, description, chairman)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data['date'],
                data['time'],
                data['segment'],
                data['track'],
                data['km_pk'],
                data['incident_type'],
                data['description'],
                data['chairman']
            )
        )
        await db.commit()

async def get_notifications(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, date, time, segment, track, km_pk, incident_type, description, chairman, created_at "
            "FROM notifications ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = await cur.fetchall()
        # возвращаем список словарей
        return [
            {
                'id':    r[0],
                'date':  r[1],
                'time':  r[2],
                'segment': r[3],
                'track': r[4],
                'km_pk': r[5],
                'type':  r[6],
                'desc':  r[7],
                'chairman': r[8],
                'created_at': r[9]
            }
            for r in rows
        ]

# --- хэндлеры команд ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    await message.reply(f"Здравствуйте, это чат-бот для уведомления о происшествиях. Ваш ID: {user_id}.")
    if user_id == ADMIN_ID:
        await message.answer(
            "Вы администратор. Выберите действие:",
            reply_markup=admin_reply_kb
        )


@dp.message(Command('add'), F.from_user.id == ADMIN_ID)
async def cmd_add(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("❗️ Использование: /add <user_id>")
    user_id_str = parts[1].strip()
    if not user_id_str.isdigit():
        return await message.reply("❗️ ID должен быть числом.")
    user_id = int(user_id_str)

    await add_user(user_id)
    await message.reply(f"✅ Пользователь с ID {user_id} подписан на оповещения.")
    
@dp.message(F.text == "📢 Заявить о происшествии", F.from_user.id == ADMIN_ID)
async def admin_notify_button(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(NotifyIncident.waiting_for_date)
    await message.answer("📅 Дата (ДД.MM.ГГГГ):")


@dp.message(F.text == "➕ Добавить пользователя", F.from_user.id == ADMIN_ID)
async def admin_add_user_button(message: types.Message):
    await message.answer("Введите команду /add <user_id> для добавления пользователя.")

@dp.message(Command('history'), F.from_user.id == ADMIN_ID)
async def cmd_history(message: types.Message):
    notifs = await get_notifications()
    if not notifs:
        return await message.reply("ℹ️ История оповещений пуста.")
    text = []
    for n in notifs:
        text.append(
            f"#{n['id']} ({n['created_at']})\n"
            f"📅 {n['date']}  🕒 {n['time']}\n"
            f"🛤 {n['segment']}  🔢 {n['track']}\n"
            f"📍 {n['km_pk']}  ⚠️ {n['type']}\n"
            f"👨‍💼 {n['chairman']}\n"
            "—\n"
        )
    # Telegram ограничивает длину, закидываем в порциях по 5
    chunk_size = 5
    for i in range(0, len(text), chunk_size):
        await message.reply("\n".join(text[i:i+chunk_size]))

# --- FSM: сбор данных и рассылка ---
@dp.message(Command('notify'), F.from_user.id == ADMIN_ID)
async def cmd_notify_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(NotifyIncident.waiting_for_date)
    await message.reply("📅 Дата (ДД.MM.ГГГГ):")

@dp.message(NotifyIncident.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(date=message.text.strip())
    await state.set_state(NotifyIncident.waiting_for_time)
    await message.reply("🕒 Время (ЧЧ:ММ):")

@dp.message(NotifyIncident.waiting_for_time)
async def process_time(message: types.Message, state: FSMContext):
    await state.update_data(time=message.text.strip())
    await state.set_state(NotifyIncident.waiting_for_segment)
    await message.reply("🛤 Перегон/станция:")

@dp.message(NotifyIncident.waiting_for_segment)
async def process_segment(message: types.Message, state: FSMContext):
    await state.update_data(segment=message.text.strip())
    await state.set_state(NotifyIncident.waiting_for_track)
    await message.reply("🔢 Путь:")

@dp.message(NotifyIncident.waiting_for_track)
async def process_track(message: types.Message, state: FSMContext):
    await state.update_data(track=message.text.strip())
    await state.set_state(NotifyIncident.waiting_for_kmpk)
    await message.reply("📍 Км ПК:")

@dp.message(NotifyIncident.waiting_for_kmpk)
async def process_kmpk(message: types.Message, state: FSMContext):
    await state.update_data(km_pk=message.text.strip())
    await state.set_state(NotifyIncident.waiting_for_type)
    await message.reply("⚠️ Вид происшествия:")

@dp.message(NotifyIncident.waiting_for_type)
async def process_type(message: types.Message, state: FSMContext):
    await state.update_data(incident_type=message.text.strip())
    await state.set_state(NotifyIncident.waiting_for_description)
    await message.reply("📝 Описание происшествия:")

@dp.message(NotifyIncident.waiting_for_description)
async def process_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(NotifyIncident.waiting_for_chairman)
    await message.reply("👨‍💼 Председатель комиссии по расследованию (ФИО):")

@dp.message(NotifyIncident.waiting_for_chairman)
async def process_chairman(message: types.Message, state: FSMContext):
    await state.update_data(chairman=message.text.strip())
    data = await state.get_data()

    # сохраняем в БД
    await add_notification(data)

    # формируем финальное сообщение
    notification = (
        "📌 Оповещение о происшествии\n\n"
        f"📅 Дата: {data['date']}\n\n"
        f"🕒 Время: {data['time']} (местное)\n\n"
        f"🛤 Перегон/станция: {data['segment']}\n\n"
        f"🔢 Путь: {data['track']}\n\n"
        f"📍 Км ПК: {data['km_pk']}\n\n"
        f"⚠️ Вид происшествия: {data['incident_type']}\n\n"
        f"📝 Описание: {data['description']}\n\n"
        f"👨‍💼 Председатель комиссии по расследованию: {data['chairman']}"
    )

    # рассылка
    users = await get_users()
    for uid in users:
        try:
            await bot.send_message(uid, notification)
        except Exception as e:
            print(f"Не удалось отправить {uid}: {e}")

    await message.reply("✅ Оповещение сохранено и отправлено всем подписчикам.")
    await state.clear()

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
