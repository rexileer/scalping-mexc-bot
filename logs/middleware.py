import json
import time
import logging
from django.utils.deprecation import MiddlewareMixin
from .models import BotLog, LogLevel
from django.conf import settings
from django.contrib.auth.models import User as DjangoUser

# Импортируем модель User из приложения users только при вызове функции
def get_telegram_user_model():
    from users.models import User
    return User

logger = logging.getLogger('django')

class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware для логирования HTTP запросов к Django-приложению
    """
    
    def process_request(self, request):
        # Сохраняем время начала обработки запроса
        request.start_time = time.time()
        return None
    
    def process_response(self, request, response):
        try:
            # Для статических файлов и favicon.ico логирование не ведём
            if (hasattr(request, 'path') and 
                (request.path.startswith(settings.STATIC_URL) or 
                 request.path.startswith(settings.MEDIA_URL) or
                 request.path == '/favicon.ico')):
                return response
            
            # Вычисляем время выполнения запроса
            if hasattr(request, 'start_time'):
                duration = time.time() - request.start_time
            else:
                duration = 0
            
            # Определяем пользователя telegram, если он есть
            user = None
            user_info = None
            
            # Если есть авторизованный пользователь Django
            if hasattr(request, 'user') and request.user.is_authenticated:
                # Записываем информацию о пользователе Django
                user_info = {
                    'django_user_id': request.user.id,
                    'django_username': request.user.username,
                    'is_staff': request.user.is_staff,
                    'is_superuser': request.user.is_superuser
                }
                
                # Если это админка, пытаемся найти связанного пользователя Telegram
                if request.path.startswith('/admin/'):
                    try:
                        # Этот импорт делаем только когда нужно
                        User = get_telegram_user_model()
                        
                        # Пытаемся найти по имени пользователя
                        telegram_user = User.objects.filter(name=request.user.username).first()
                        if telegram_user:
                            user = telegram_user
                            user_info['telegram_id'] = telegram_user.telegram_id
                    except Exception as e:
                        logger.error(f"Ошибка при поиске пользователя Telegram: {e}")
            
            # Определяем уровень логирования на основе кода ответа
            if 500 <= response.status_code < 600:
                level = LogLevel.ERROR
            elif 400 <= response.status_code < 500:
                level = LogLevel.WARNING
            else:
                level = LogLevel.INFO
            
            # Подготовка данных запроса для логирования
            request_data = {
                'method': request.method,
                'path': request.path,
                'status_code': response.status_code,
                'duration': f"{duration:.2f}s",
                'user_agent': request.META.get('HTTP_USER_AGENT', 'Unknown'),
                'ip': self.get_client_ip(request),
                'user_info': user_info
            }
            
            # Только если запрос не к админке, мы логируем параметры запроса
            if not request.path.startswith('/admin/'):
                # POST данные
                if request.method == 'POST' and hasattr(request, 'POST'):
                    try:
                        request_data['post_data'] = {k: v for k, v in request.POST.items() 
                                                    if k.lower() not in ('password', 'api_key', 'api_secret', 'token')}
                    except:
                        pass
                
                # GET параметры
                if hasattr(request, 'GET') and request.GET:
                    request_data['get_params'] = dict(request.GET)
            
            # Создаем запись лога
            message = f"{request.method} {request.path} - {response.status_code}"
            
            BotLog.objects.create(
                level=level,
                message=message,
                user=user,  # Может быть None или объект User из модели telegram
                extra_data=request_data
            )
            
        except Exception as e:
            logger.error(f"Ошибка в RequestLoggingMiddleware: {e}")
        
        return response
    
    def get_client_ip(self, request):
        """Получает IP-адрес клиента из запроса"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR', 'Unknown')
        return ip 