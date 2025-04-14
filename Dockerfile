FROM python:3.11

# Устанавливаем Node.js + локали
RUN apt-get update && \
    apt-get install -y curl gnupg build-essential locales && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    locale-gen ru_RU.UTF-8 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y locales 
RUN locale-gen ru_RU.UTF-8
ENV LANG=ru_RU.UTF-8
    

WORKDIR /app

COPY . /app/

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000
