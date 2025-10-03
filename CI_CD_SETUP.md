# CI/CD Setup Guide

## Обзор
Проект использует GitHub Actions для автоматического тестирования и деплоя в dev окружение.

## Workflow

### 1. Тестирование (Test Job)
Запускается при:
- Push в ветку `dev`
- Pull request в ветку `dev`

Шаги:
1. Checkout кода
2. Установка Python 3.11
3. Установка зависимостей
4. Запуск PostgreSQL в контейнере
5. Применение миграций Django
6. Запуск pytest тестов

### 2. Деплой (Deploy Job)
Запускается только при:
- Успешном прохождении тестов
- Push в ветку `dev` (не PR)

Шаги:
1. Подключение к серверу по SSH
2. Переход в директорию проекта (`~/scalping-mexc-bot`)
3. Git pull из ветки dev
4. Перезапуск Docker контейнеров
5. Проверка статуса сервисов

## Настройка GitHub Secrets

### Необходимые secrets в environment "development":

1. **DEPLOY_HOST**
   - Адрес вашего сервера (IP или домен)
   - Пример: `192.168.1.100` или `dev.example.com`

2. **DEPLOY_USER**
   - Имя пользователя для SSH подключения
   - Пример: `ubuntu`, `root`, `deployer`

3. **DEPLOY_PASSWORD**
   - Пароль для SSH подключения
   - ⚠️ Рекомендуется использовать SSH ключи вместо пароля

### Как добавить secrets:

1. Перейдите в Settings → Environments
2. Создайте environment с именем `development`
3. Добавьте secrets:
   - Нажмите "Add Secret"
   - Введите имя и значение
   - Сохраните

## Структура тестов

```
tests/
├── __init__.py
├── test_models.py      # Тесты моделей Django
├── test_utils.py       # Тесты утилит
└── test_config.py      # Тесты конфигурации
```

### Запуск тестов локально

```bash
# Установите pytest
pip install pytest pytest-django pytest-asyncio

# Создайте .env файл с тестовыми данными
cp .env.example .env

# Запустите тесты
pytest tests/ -v
```

## Структура Workflow

```yaml
test (всегда) → deploy (только при push в dev)
```

## Логи и мониторинг

### Просмотр логов workflow:
1. Перейдите в вкладку "Actions" в GitHub
2. Выберите нужный workflow run
3. Кликните на job для просмотра логов

### Что проверять:
- ✅ Все тесты прошли успешно
- ✅ Деплой завершился без ошибок
- ✅ Сервисы запустились корректно

## Troubleshooting

### Тесты падают
1. Проверьте логи в GitHub Actions
2. Запустите тесты локально для debugging
3. Проверьте миграции БД

### Деплой не срабатывает
1. Проверьте, что push в ветку `dev`
2. Убедитесь, что тесты прошли успешно
3. Проверьте secrets в environment

### SSH подключение не работает
1. Проверьте правильность DEPLOY_HOST, DEPLOY_USER, DEPLOY_PASSWORD
2. Убедитесь, что сервер доступен
3. Проверьте firewall правила на сервере

### Docker контейнеры не перезапускаются
1. Проверьте наличие docker-compose.yml на сервере
2. Убедитесь, что Docker и Docker Compose установлены
3. Проверьте права пользователя на выполнение docker команд

## Улучшения в будущем

### Рекомендуется:
- [ ] Использовать SSH ключи вместо пароля
- [ ] Добавить уведомления в Telegram о деплое
- [ ] Настроить staging окружение
- [ ] Добавить rollback механизм
- [ ] Увеличить покрытие тестами
- [ ] Добавить linting (flake8, black, isort)
- [ ] Настроить code coverage отчеты

### SSH ключи (рекомендуется):
```yaml
# Замените password на key в workflow:
with:
  host: ${{ secrets.DEPLOY_HOST }}
  username: ${{ secrets.DEPLOY_USER }}
  key: ${{ secrets.DEPLOY_SSH_KEY }}
```

## Безопасность

### ⚠️ Важно:
- Никогда не коммитьте .env файлы
- Используйте GitHub Secrets для чувствительных данных
- Ограничьте доступ к environment в Settings
- Регулярно меняйте пароли и ключи

## Поддержка

При возникновении проблем:
1. Проверьте логи в GitHub Actions
2. Проверьте логи на сервере: `docker-compose logs`
3. Проверьте статус сервисов: `docker-compose ps`

