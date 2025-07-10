import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime
from aiohttp import web
from skyfield.api import load
import g4f
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise ValueError("❌ Переменная окружения BOT_TOKEN не установлена")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
user_data = {}

LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "-1002899360000"))  # можно тоже вынести

tarot_cache = {}
chart_cache = {}

planets = load('de421.bsp')
ts = load.timescale()

menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Гадание на Таро")],
              [KeyboardButton(text="Натальная карта")]],
    resize_keyboard=True)


def generate_tarot_prompt(user_input: str) -> str:
    return f"""
Ты — опытный таролог с многолетней практикой. Не используй смайлики и ссылки.
Сделай мистический текстовый расклад по запросу пользователя, укажи 3 карты и поясни каждую.

Запрос:
{user_input}

Ответ должен быть эзотерическим, ясным, красивым.
"""


def generate_chart_prompt(user_input: str) -> str:
    return f"""
Ты — профессиональный астролог. Не используй смайлики и ссылки.
Проанализируй положение планет и сделай краткую интерпретацию личности и судьбы пользователя.

Данные:
{user_input}

Сделай красивый и глубокий астрологический разбор.
"""


def get_zodiac(sign_index):
    signs = [
        "Овна", "Тельца", "Близнецов", "Рака", "Льва", "Девы", "Весов",
        "Скорпиона", "Стрельца", "Козерога", "Водолея", "Рыб"
    ]
    return signs[sign_index]


async def log_usage(user: types.User, type_: str, query: str):
    username = user.username or f"{user.first_name} {user.last_name or ''}".strip()
    await bot.send_message(
        LOG_CHAT_ID, f"🔮 Новый {type_}:\n"
        f"👤 Пользователь: @{username} (ID: {user.id})\n"
        f"📝 Запрос: {query}\n"
        f"⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_data[message.from_user.id] = {'state': 'menu'}
    await message.answer("Выберите, что вы хотите узнать:", reply_markup=menu_keyboard)


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id not in user_data:
        user_data[user_id] = {'state': 'menu'}

    state = user_data[user_id].get('state')

    if state == 'menu':
        if text == "Гадание на Таро":
            user_data[user_id]['state'] = 'tarot_waiting'
            await message.answer("Введите своё имя, возраст и тему расклада (например: Анна, 24, любовь):")

        elif text == "Натальная карта":
            user_data[user_id]['state'] = 'chart_waiting'
            await message.answer("Введите дату, время и место рождения (пример: 12.03.1995, 14:45, Москва).\n"
                                 "Если точное время рождения неизвестно, укажите 12:00.")
        else:
            await message.answer("Пожалуйста, выберите опцию с клавиатуры.")

    elif state == 'tarot_waiting':
        await message.answer("Делаю расклад, подождите немного...")

        if text in tarot_cache:
            response = tarot_cache[text]
        else:
            try:
                response = g4f.ChatCompletion.create(
                    model=g4f.models.gpt_4,
                    messages=[
                        {"role": "system", "content": "Ты — профессиональный таролог. Не используй смайлики и ссылки."},
                        {"role": "user", "content": generate_tarot_prompt(text)}
                    ])
                tarot_cache[text] = response
            except Exception as e:
                await message.answer("Произошла ошибка при обращении к нейросети.")
                print(f"Ошибка: {e}")
                user_data[user_id]['state'] = 'menu'
                return

        await message.answer(f"Ваш расклад:\n\n{response}")
        await log_usage(message.from_user, "расклад Таро", text)
        user_data[user_id]['state'] = 'menu'

    elif state == 'chart_waiting':
        await message.answer("Смотрю вашу натальную карту...")
        try:
            parts = [x.strip() for x in text.split(",")]
            if len(parts) != 3:
                raise ValueError("Неверное количество параметров. Нужно 3: дата, время, город.")
            date_part, time_part, city = parts

            day, month, year = map(int, date_part.split("."))
            hour, minute = map(int, time_part.split(":"))

            birth_dt = datetime(year, month, day, hour, minute)
            cache_key = text

            if cache_key in chart_cache:
                response = chart_cache[cache_key]
            else:
                t = ts.utc(year, month, day, hour, minute)
                earth = planets['earth']

                planet_names_codes = [
                    ("Солнце", 'sun'), ("Луна", 'moon'), ("Меркурий", 'mercury'),
                    ("Венера", 'venus'), ("Марс", 'mars'), ("Юпитер", 'jupiter barycenter'),
                    ("Сатурн", 'saturn barycenter'),
                ]

                positions = []
                for name, key in planet_names_codes:
                    body = planets[key]
                    astrometric = earth.at(t).observe(body)
                    lon, lat, dist = astrometric.ecliptic_latlon()
                    lon_deg = lon.degrees % 360
                    sign = int(lon_deg // 30)
                    deg_in_sign = lon_deg % 30
                    positions.append(f"{name}: {deg_in_sign:.1f}° в знаке {get_zodiac(sign)}")

                planet_text = "\n".join(positions)
                astro_input = f"Город: {city}\nДата: {birth_dt.strftime('%d.%m.%Y %H:%M')}\n\nПланеты:\n{planet_text}"

                response = g4f.ChatCompletion.create(
                    model=g4f.models.gpt_4,
                    messages=[
                        {"role": "system", "content": "Ты — профессиональный астролог. Не используй смайлики и ссылки."},
                        {"role": "user", "content": generate_chart_prompt(astro_input)}
                    ])
                chart_cache[cache_key] = response

            await message.answer(f"Натальная карта:\n\n{response}")
            await log_usage(message.from_user, "натальная карта", text)

        except Exception as e:
            await message.answer(
                "Произошла ошибка. Проверьте формат ввода. Пример:\n"
                "12.03.1995, 14:45, Москва\n"
                "Если точное время неизвестно — укажите 12:00.")
            print(f"Ошибка при разборе даты/времени/города: {e}")

        user_data[user_id]['state'] = 'menu'

    else:
        await message.answer("Пожалуйста, начните с /start")


async def handle(request):
    return web.Response(text="Bot is alive!")


async def start_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()


if __name__ == "__main__":
    print("Бот запущен...")

    async def main():
        asyncio.create_task(start_web())
        await dp.start_polling(bot)

    asyncio.run(main())
