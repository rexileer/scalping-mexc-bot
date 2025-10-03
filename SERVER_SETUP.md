# Server Setup Guide

Краткое руководство по подготовке сервера для автоматического деплоя.

## Требования на сервере

- Ubuntu/Debian Linux
- Git
- Docker & Docker Compose
- SSH доступ

## Первоначальная настройка

### 1. Подключиться к серверу

```bash
ssh your_user@your_server_ip
```

### 2. Установить Docker

```bash
# Обновить пакеты
sudo apt update
sudo apt upgrade -y

# Установить Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Добавить пользователя в группу docker
sudo usermod -aG docker $USER

# Применить изменения (или перелогиниться)
newgrp docker

# Проверить установку
docker --version
```

### 3. Установить Docker Compose

```bash
# Установить Docker Compose
sudo apt install docker-compose -y

# Проверить установку
docker-compose --version
```

### 4. Установить Git (если не установлен)

```bash
sudo apt install git -y
git --version
```

### 5. Клонировать репозиторий

```bash
# Перейти в домашнюю директорию
cd ~

# Клонировать репозиторий
git clone https://github.com/yourusername/skalping_bot.git scalping-mexc-bot

# Перейти в директорию
cd scalping-mexc-bot

# Переключиться на dev ветку
git checkout dev
```

### 6. Создать .env файл

```bash
# Скопировать пример
cp env.example .env

# Отредактировать файл
nano .env
```

Заполнить необходимые переменные:
```env
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=False
POSTGRES_DB=scalping_db
POSTGRES_USER=scalping_user
POSTGRES_PASSWORD=your-secure-password
POSTGRES_HOST=scalpingdb
POSTGRES_PORT=5432
TELEGRAM_TOKEN=your-telegram-bot-token
NOTIFICATION_CHAT_ID=your-admin-chat-id
PAIR=BTCUSDT
```

### 7. Первый запуск

```bash
# Запустить сервисы
docker-compose up -d --build

# Проверить статус
docker-compose ps

# Применить миграции
docker-compose exec scalpingweb python manage.py migrate

# Создать суперпользователя (опционально)
docker-compose exec scalpingweb python manage.py createsuperuser

# Проверить логи
docker-compose logs -f
```

## Проверка автоматического деплоя

### 1. Проверить, что проект в правильной директории

```bash
ls -la ~/scalping-mexc-bot
```

Должны увидеть файлы проекта: `docker-compose.yml`, `manage.py`, и т.д.

### 2. Убедиться, что Docker работает без sudo

```bash
docker ps
```

Если ошибка "permission denied", выполнить:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### 3. Проверить доступ к Git

```bash
cd ~/scalping-mexc-bot
git pull origin dev
```

Должно успешно подтянуть изменения.

### 4. Тестовый деплой вручную

```bash
cd ~/scalping-mexc-bot
git pull origin dev
docker-compose down
docker-compose up -d --build
docker-compose ps
```

Все сервисы должны быть в статусе "Up".

## Настройка GitHub Secrets

### В GitHub репозитории:

1. Перейти в **Settings** → **Environments**
2. Создать environment **development**
3. Добавить secrets:

**DEPLOY_HOST**
```
Ваш IP адрес или домен сервера
Пример: 192.168.1.100
```

**DEPLOY_USER**
```
Имя пользователя на сервере
Пример: ubuntu
```

**DEPLOY_PASSWORD**
```
Пароль пользователя для SSH
```

## Тестирование CI/CD

### 1. Сделать тестовый коммит в dev

```bash
# На локальной машине
git checkout dev
echo "# Test" >> test.txt
git add test.txt
git commit -m "test: CI/CD deployment"
git push origin dev
```

### 2. Проверить GitHub Actions

1. Перейти в вкладку **Actions** в GitHub
2. Найти workflow run
3. Дождаться завершения Test job
4. Проверить Deploy job

### 3. Проверить на сервере

```bash
# На сервере
cd ~/scalping-mexc-bot
git log -1  # Должен показать последний коммит
docker-compose ps  # Все сервисы должны быть Up
```

## Полезные команды

### Просмотр логов

```bash
# Все сервисы
docker-compose logs -f

# Конкретный сервис
docker-compose logs -f scalpingbot

# Последние 100 строк
docker-compose logs --tail=100 scalpingbot
```

### Перезапуск сервисов

```bash
# Перезапустить все
docker-compose restart

# Перезапустить конкретный сервис
docker-compose restart scalpingbot

# Полный перезапуск с пересборкой
docker-compose down
docker-compose up -d --build
```

### Очистка

```bash
# Удалить остановленные контейнеры
docker container prune -f

# Удалить неиспользуемые образы
docker image prune -a -f

# Удалить неиспользуемые volumes
docker volume prune -f

# Полная очистка
docker system prune -a -f
```

### Мониторинг ресурсов

```bash
# Использование ресурсов контейнерами
docker stats

# Использование диска
df -h

# Логи системы
journalctl -u docker -f
```

## Troubleshooting

### Проблема: Контейнеры не запускаются

```bash
# Проверить логи
docker-compose logs

# Проверить ресурсы
docker stats
free -h
df -h

# Пересоздать контейнеры
docker-compose down -v
docker-compose up -d --build
```

### Проблема: База данных не доступна

```bash
# Проверить статус PostgreSQL
docker-compose ps scalpingdb

# Проверить логи БД
docker-compose logs scalpingdb

# Перезапустить БД
docker-compose restart scalpingdb
```

### Проблема: Git pull не работает

```bash
# Проверить статус репозитория
git status

# Сбросить изменения
git reset --hard origin/dev

# Обновить
git pull origin dev
```

### Проблема: Недостаточно места

```bash
# Проверить использование диска
df -h

# Очистить Docker
docker system prune -a -f

# Очистить старые логи
find /var/log -type f -name "*.log" -mtime +7 -delete
```

## Безопасность

### Рекомендации:

1. **Использовать SSH ключи вместо паролей**
```bash
# На локальной машине
ssh-keygen -t rsa -b 4096
ssh-copy-id user@server
```

2. **Настроить firewall**
```bash
sudo ufw allow 22/tcp
sudo ufw allow 8000/tcp
sudo ufw enable
```

3. **Регулярные обновления**
```bash
sudo apt update
sudo apt upgrade -y
```

4. **Резервное копирование**
```bash
# Backup базы данных
docker-compose exec scalpingdb pg_dump -U scalping_user scalping_db > backup.sql

# Backup .env
cp .env .env.backup
```

## Мониторинг

### Настроить автоматические уведомления

Добавить в cron для мониторинга:
```bash
crontab -e
```

Добавить:
```
# Проверка сервисов каждые 5 минут
*/5 * * * * cd ~/scalping-mexc-bot && docker-compose ps | grep -q "Up" || echo "Services down!" | mail -s "Alert" your@email.com
```

## Поддержка

При проблемах:
1. Проверить логи: `docker-compose logs`
2. Проверить статус: `docker-compose ps`
3. Проверить GitHub Actions
4. Создать issue в репозитории

