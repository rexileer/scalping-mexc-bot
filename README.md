# Skalping Bot 🤖

Telegram-бот для автоматической торговли на криптобирже MEXC с использованием стратегии скальпинга.

## 📋 Возможности

- ✅ Автоматическая торговля (autobuy) с настраиваемыми триггерами
- ✅ WebSocket соединения для real-time данных
- ✅ Управление торговыми параметрами через Telegram
- ✅ Система подписок для пользователей
- ✅ Мониторинг и логирование операций
- ✅ CI/CD с автоматическим тестированием и деплоем

## 🛠 Технологии

- **Backend**: Python 3.11, Django 5.2
- **Database**: PostgreSQL
- **Bot Framework**: aiogram 3.19.0
- **API Integration**: MEXC REST + WebSocket API
- **Containerization**: Docker, Docker Compose
- **CI/CD**: GitHub Actions

## 🚀 Быстрый старт

### Требования
- Python 3.11+
- PostgreSQL
- Docker & Docker Compose (для production)
- Telegram Bot Token
- MEXC API credentials

### Установка

1. **Клонировать репозиторий**
```bash
git clone https://github.com/yourusername/skalping_bot.git
cd skalping_bot
```

2. **Создать виртуальное окружение**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

3. **Установить зависимости**
```bash
pip install -r requirements.txt
```

4. **Настроить переменные окружения**
```bash
cp env.example .env
# Отредактировать .env файл с вашими данными
```

5. **Применить миграции**
```bash
python manage.py migrate
```

6. **Создать суперпользователя**
```bash
python manage.py createsuperuser
```

7. **Запустить бота**
```bash
python bot/tg_bot.py
```

## 🐳 Docker Deployment

### Запуск через Docker Compose

```bash
# Сборка и запуск всех сервисов
docker-compose up -d --build

# Просмотр логов
docker-compose logs -f

# Остановка сервисов
docker-compose down
```

### Сервисы
- `scalpingdb` - PostgreSQL база данных
- `scalpingweb` - Django web приложение (порт 8000)
- `scalpingbot` - Telegram бот

## 🧪 Тестирование

### Запуск тестов

```bash
# Все тесты
pytest tests/ -v

# Конкретный файл
pytest tests/test_models.py -v

# С подробным выводом
pytest tests/ -vv --tb=short
```

### Структура тестов
```
tests/
├── test_models.py      # Тесты моделей Django
├── test_utils.py       # Тесты утилит
└── test_config.py      # Тесты конфигурации
```

## 🔄 CI/CD

### GitHub Actions Workflow

Автоматический CI/CD настроен для ветки `dev`:

1. **Test Job** - Запуск тестов при каждом push/PR
2. **Deploy Job** - Автоматический деплой при push в dev

### Настройка

1. Создать environment `development` в GitHub
2. Добавить secrets:
   - `DEPLOY_HOST` - IP/домен сервера
   - `DEPLOY_USER` - SSH пользователь
   - `DEPLOY_PASSWORD` - SSH пароль

Подробнее: [CI/CD Setup Guide](CI_CD_SETUP.md)

## 📚 Документация

### Memory Bank
- [Project Brief](memory-bank/projectbrief.md) - Обзор проекта
- [Product Context](memory-bank/productContext.md) - Описание продукта
- [System Patterns](memory-bank/systemPatterns.md) - Архитектура
- [Tech Context](memory-bank/techContext.md) - Технологии
- [Active Context](memory-bank/activeContext.md) - Текущее состояние
- [Progress](memory-bank/progress.md) - Прогресс и планы
- [CI/CD](memory-bank/cicd.md) - CI/CD документация

### Дополнительно
- [CI/CD Setup](CI_CD_SETUP.md) - Настройка CI/CD
- [.cursorrules](.cursorrules) - Правила проекта

## 🔧 Конфигурация

### Environment Variables

```env
# Django
DJANGO_SECRET_KEY=your-secret-key
DEBUG=False

# PostgreSQL
POSTGRES_DB=scalping_db
POSTGRES_USER=scalping_user
POSTGRES_PASSWORD=your-password
POSTGRES_HOST=scalpingdb
POSTGRES_PORT=5432

# Telegram
TELEGRAM_TOKEN=your-bot-token
NOTIFICATION_CHAT_ID=admin-chat-id

# Trading
PAIR=BTCUSDT
```

## 📊 Структура проекта

```
skalping_bot/
├── bot/                    # Telegram бот
│   ├── commands/          # Команды бота
│   ├── utils/             # Утилиты
│   ├── middlewares/       # Middleware
│   └── tg_bot.py         # Главный файл
├── core/                  # Django настройки
├── users/                 # Пользователи
├── subscriptions/         # Подписки
├── parameters/            # Параметры
├── logs/                  # Логирование
├── tests/                 # Тесты
├── memory-bank/           # Документация
├── .github/workflows/     # CI/CD
└── docker-compose.yml     # Docker конфигурация
```

## 🤝 Contributing

1. Fork репозиторий
2. Создать feature branch (`git checkout -b feature/amazing-feature`)
3. Commit изменения (`git commit -m 'Add amazing feature'`)
4. Push в branch (`git push origin feature/amazing-feature`)
5. Открыть Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🐛 Issues & Support

При возникновении проблем:
1. Проверьте [документацию](memory-bank/)
2. Создайте [issue](https://github.com/yourusername/skalping_bot/issues)
3. Проверьте логи: `docker-compose logs`

## ⚠️ Disclaimer

Этот бот предназначен для образовательных целей. Торговля криптовалютами связана с рисками. Используйте на свой страх и риск.

## 📈 Roadmap

- [ ] SSH ключи для деплоя
- [ ] Уведомления в Telegram о деплое
- [ ] Staging окружение
- [ ] Расширенная аналитика
- [ ] Machine learning для прогнозирования
- [ ] Multi-exchange support
- [ ] Mobile-friendly интерфейс

## 👥 Authors

- Your Name - Initial work

## 🙏 Acknowledgments

- MEXC API
- aiogram framework
- Django community
