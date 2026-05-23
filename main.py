import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters
from telegram.request import HTTPXRequest
from google import genai
from google.genai import types

# Загружаем токены
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROXY_URL = os.getenv("PROXY_URL")

# Проверка загрузки токенов
print("=" * 50)
print("ПРОВЕРКА ЗАГРУЗКИ ТОКЕНОВ:")
print(f"TELEGRAM_TOKEN: {TELEGRAM_TOKEN[:10]}...{TELEGRAM_TOKEN[-5:] if TELEGRAM_TOKEN else 'НЕ НАЙДЕН'}")
print(f"GEMINI_API_KEY: {GEMINI_API_KEY[:10]}...{GEMINI_API_KEY[-5:] if GEMINI_API_KEY else 'НЕ НАЙДЕН'}")
print(f"PROXY_URL: {PROXY_URL.split('@')[-1] if PROXY_URL else 'НЕ НАЙДЕН'}")
print("=" * 50)

if not TELEGRAM_TOKEN:
    print("ОШИБКА: TELEGRAM_TOKEN не найден в .env файле!")
    exit(1)
if not GEMINI_API_KEY:
    print("ОШИБКА: GEMINI_API_KEY не найден в .env файле!")
    exit(1)

# Устанавливаем прокси
if PROXY_URL:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL
    os.environ['ALL_PROXY'] = PROXY_URL
    print(f"Прокси установлен: {PROXY_URL.split('@')[-1]}")
else:
    print("ВНИМАНИЕ: Прокси не используется")

start_time = datetime.now()
total_requests = 0
hourly_requests = []

def add_request():
    global total_requests, hourly_requests
    total_requests += 1
    hourly_requests.append(datetime.now())
    one_hour_ago = datetime.now() - timedelta(hours=1)
    hourly_requests = [t for t in hourly_requests if t > one_hour_ago]
    print(f"Статистика обновлена: всего {total_requests}, за час {len(hourly_requests)}")

def get_hourly_count():
    one_hour_ago = datetime.now() - timedelta(hours=1)
    return sum(1 for t in hourly_requests if t > one_hour_ago)

def get_uptime():
    uptime = datetime.now() - start_time
    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    seconds = uptime.seconds % 60
    if days > 0:
        return f"{days}д {hours}ч {minutes}м {seconds}с"
    elif hours > 0:
        return f"{hours}ч {minutes}м {seconds}с"
    elif minutes > 0:
        return f"{minutes}м {seconds}с"
    else:
        return f"{seconds}с"

#модели который будут выбераться (выбор идет сверху вниз)
MODELS = [
    "gemini-3.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

print("Инициализация")
client = genai.Client(api_key=GEMINI_API_KEY)
print("клиент готов")

async def extract_landmark_name(response_text):
    lines = response_text.split('\n')
    for line in lines[:3]:
        line = line.strip()
        if len(line) > 3 and len(line) < 100:
            name = line.lstrip('*-•0123456789. ')
            if name and not name.startswith(('Что', 'Как', 'Это', 'На', 'Расскажи')):
                return name[:60]
    return response_text[:40]

async def analyze_photo(img_bytes):
    print(f"анализ фото (размер: {len(img_bytes)} байт)")
    
    for model_name in MODELS:
        print(f"модель: {model_name}")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    "Назови одним-двумя словами, что изображено на этом фото. Затем напиши краткую информацию.Так же если на фотке нету не какой достопримечательности напиши данное сообщение (просто это сообщение не нужно расписывать что изображено на картинке просто этот текст и все): На данном фото отсутсвует достопримечательность. ",
                    types.Part.from_bytes(data=bytes(img_bytes), mime_type="image/jpeg")
                ]
            )
            print(f"модель {model_name} ответила успешно")
            return response.text, model_name
        except Exception as e:
            print(f"ошибка {model_name}: {str(e)[:200]}")
            await asyncio.sleep(1)
    
    print("все модели не сработали") #плохой знак отвалилась либо апишка джемени либо прокси (файл .env)
    return "❌ Не удалось обработать фото", None

async def handle_photo(update: Update, context):
    print("получено фото")
    
    # Отправляем сообщение пользователю
    await update.message.reply_text("🔍 Анализирую фото. В среднем занимает около 10 - 25 секунд")
    print("сообщение доставлено пользавателю")

    try:
        print("фото загружаеться")
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        print(f"размер: {len(img_bytes)} байт")
        
        print("Отправляю в нейронку")
        result, used_model = await analyze_photo(bytes(img_bytes))
        
        if result and "❌" not in result:
            landmark_name = await extract_landmark_name(result)
            add_request()
            
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{current_time}] краткий ответ: {landmark_name}")
            print(f"от {used_model}")
            print(f" {total_requests} {get_hourly_count()}  {get_uptime()}")
            
            await update.message.reply_text(f"🏛️ {result}")
            print("ответ отправлен пользователю")
        else:
            print(f"ошибка: {result}")
            await update.message.reply_text(result or "❌ Не удалось обработать фото")
            print("сообщение об ошибке отправлено")

    except Exception as e:
        error_msg = str(e)
        print(f"очень плохая ошибка{error_msg}") #проверить саму ошибку 404 поменять модели на актуальные другая проверить апишки из файла .env
        import traceback
        traceback.print_exc()
        await update.message.reply_text(f"❌ Ошибка: {error_msg[:200]}")
        print("cообщение об ошибке отправлено")

def main():
    print("ЗАПУСК БОТА")
    
    # Настройка прокси для тг
    if PROXY_URL:
        proxy_request = HTTPXRequest(proxy=PROXY_URL)
        app = Application.builder().token(TELEGRAM_TOKEN).request(proxy_request).build()
        print(f"бот настроен с прокси")
    else:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        print(f"бот настроен без прокси")
    
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    print(f"Модели: {', '.join(MODELS)}")
    print(f"дата запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("все работает.")
    
    app.run_polling()

if __name__ == "__main__":
    main()