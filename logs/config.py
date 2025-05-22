class LogConfig:
    # Количество дней хранения логов
    RETENTION_DAYS = 7
    
    # Включить/выключить автоматическую очистку старых логов
    AUTO_CLEANUP_ENABLED = True
    
    # Префиксы для сообщений логов
    PREFIXES = {
        'BOT_START': '[БОТ] Запуск',
        'BOT_STOP': '[БОТ] Остановка',
        'USER_ACTION': '[ПОЛЬЗОВАТЕЛЬ]',
        'API_CALL': '[API]',
        'SYSTEM': '[СИСТЕМА]',
    }

# Настройки логирования для различных компонентов
LOG_COMPONENTS = {
    'bot': {
        'enabled': True,
        'levels': ['INFO', 'WARNING', 'ERROR'],
    },
    'api': {
        'enabled': True,
        'levels': ['WARNING', 'ERROR'],
    },
    'user_actions': {
        'enabled': True,
        'levels': ['INFO', 'WARNING', 'ERROR'],
    },
    'system': {
        'enabled': True,
        'levels': ['INFO', 'WARNING', 'ERROR', 'DEBUG'],
    }
} 