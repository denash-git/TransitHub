# Документация 3XUI V2

## Назначение проекта

Этот репозиторий разворачивает `3x-ui` на чистой VPS как одноразовый installer-проект.
Основная идея такая:

- репозиторий клонируется на свежую VPS
- запускается `bash install.sh`
- установщик готовит хост, рендерит конфиги, поднимает контейнеры и настраивает панель
- после успешной установки install-time часть удаляется, на сервере остаётся только runtime

Поддерживаемый целевой сценарий:

- Debian 12
- Debian 13

## Быстрая установка

Рабочий минимальный сценарий:

```bash
apt-get update
apt-get install -y git
git clone https://github.com/denash-git/3xui ~/3xui
cd ~/3xui
bash install.sh
```

Можно запускать:

- от `root`
- от пользователя с `sudo`

Если скрипт запущен не от `root`, он сам попытается перезапуститься через `sudo`.

## Что спрашивает install.sh

Во время запуска инсталлер спрашивает:

- `Main domain`
  Основной домен панели, клиентской страницы и подписок
- `REALITY domain`
  REALITY SNI-домен
- `MTProxy TLS domain`
  необязательный SNI-домен для официального Telegram MTProxy в TLS-only режиме; если оставить пустым, MTProxy не поднимается
- `Timezone`
  timezone контейнеров; по умолчанию берётся timezone VPS

Fake-site шаблон выбирается автоматически.

## Что проверяется до установки

Перед основной установкой выполняется preflight:

- есть ли права `root`
- доступен ли `apt-get`
- действительно ли это Debian 12/13
- свободны ли порты `80` и `443`
- не конфликтует ли Docker network `proxy-net`
- резолвится ли основной домен

Если какая-то из проверок не проходит, установка останавливается сразу с понятным сообщением.

## Этапы установки

Инсталлер идёт по шагам:

1. preflight-проверки
2. подготовка `.venv`
3. установка Python-зависимостей
4. создание layout проекта
5. установка системных пакетов, Docker, Compose и настройка `ufw`
6. генерация `instance.env` и runtime-файлов
7. выпуск или повторное использование TLS-сертификата
8. запуск `xui`, `conv` и опционально `mtproxy`
9. первичная настройка `x-ui.db`
10. запуск полного стека и очистка install-time файлов

Долгие этапы теперь выводят дополнительные подпункты, чтобы было видно, что именно происходит.

## Структура проекта в репозитории

До установки репозиторий содержит:

- `install.sh`
  Пользовательская точка входа
- `instance.env.example`
  Пример конфигурации
- `requirements.txt`
  Python-зависимости installer-части
- `install/`
  Внутренняя логика установщика
- `templates/`
  Шаблоны nginx, client page, fake-site и clash
- `nginx/`
  Runtime-каталог nginx
- `xui/`
  Runtime-каталог `3x-ui`
- `subconverter/`
  Runtime-каталог конвертера
- `web/`
  Статические web-ресурсы
- `docs/`
  Документация

## Что остаётся на VPS после успешной установки

После успешного деплоя Linux-установка вычищает:

- `.venv`
- `install/`
- `templates/`
- `docs/`
- `README.md`
- `requirements.txt`
- `install.sh`
- `instance.env.example`

Итоговое runtime-дерево на VPS:

- `instance.env`
- `nginx/`
- `xui/`
- `subconverter/`
- `web/`

## Runtime-структура

### Корень проекта

- `instance.env`
  Главный сгенерированный конфиг экземпляра

### Nginx

- `nginx/config/nginx.conf`
  Основной nginx config
- `nginx/config/stream.conf`
  Stream-проксирование для REALITY
- `nginx/config/site.conf`
  HTTP/HTTPS routing
- `nginx/extensions/`
  Дополнительные nginx include-файлы
- `nginx/docker-compose.yml`
  Compose-описание nginx

### 3x-ui

- `xui/data/x-ui.db`
  Главная SQLite-база панели
- `xui/docker-compose.yml`
  Compose-описание `xui`

### Конвертер

- `subconverter/data/`
  Данные контейнера `tindy2013/subconverter`
- `subconverter/docker-compose.yml`
  Compose-описание сервиса `conv`

### Веб-ресурсы

- `web/client_page/index.html`
  Страница клиента
- `web/client_page/clash.yaml`
  Сгенерированный Clash-конфиг
- `web/fake_site/index.html`
  Fake-site заглушка

## Docker-схема

Используются три compose-файла:

- `nginx/docker-compose.yml`
- `xui/docker-compose.yml`
- `subconverter/docker-compose.yml`

Все сервисы подключаются к внешней сети:

- `proxy-net`

Если сети ещё нет, установщик создаёт её сам.

Сервисы:

- `nginx`
  Единственный сервис с публикацией наружу `80:80` и `443:443`
- `xui`
  Панель и subscription backend
- `conv`
  Конвертер подписок на базе `tindy2013/subconverter`

## Что настраивается в 3x-ui автоматически

Во время `seed-xui-db` установщик:

- задаёт логин и пароль панели
- задаёт `webBasePath`
- выставляет `timeLocation`
- включает subscription-функции
- выставляет `sessionMaxAge=30`
- создаёт базовые inbound'ы:
  - `reality`
  - `ws`
  - `xhttp`
  - `trojan-grpc`

## Основные значения в instance.env

Наиболее важные поля:

- `DOMAIN`
  основной домен
- `REALITY_DOMAIN`
  REALITY domain
- `TZ`
  timezone контейнеров
- `PANEL_PATH`
  внешний путь панели
- `SUB_PATH`
  путь обычной подписки
- `JSON_PATH`
  путь JSON-подписки
- `WEB_PATH`
  путь клиентской страницы
- `SUBCONVERTER_PATH`
  путь конвертера
- `CONFIG_USERNAME`
  логин панели
- `CONFIG_PASSWORD`
  пароль панели

## Firewall и внешние порты

Установщик настраивает `ufw` так:

- `deny incoming`
- `allow outgoing`
- `allow 22/tcp`
- `allow 80/tcp`
- `allow 443/tcp`

Наружу публикуются только:

- `80`
- `443`

Остальные сервисные порты остаются внутренними в Docker network.

## Почему не требуется открывать остальные порты

`xui` и `conv` не публикуются напрямую на хост.
Снаружи доступен только `nginx`, который маршрутизирует запросы внутрь Docker-сети.

## Поведение на Debian 12 и Debian 13

Сейчас installer ориентирован именно на Debian 12/13:

- использует `apt-get`
- ставит `docker.io`
- пробует сначала `docker-compose-plugin`, затем fallback на `docker-compose`
- автоматически ставит `python3-venv`, если его нет

То есть сценарий Debian 13 тоже считается штатным.

## Если запускать не от root

Поддерживаются два варианта:

- `root`
- обычный пользователь с `sudo`

Если запустить:

```bash
bash install.sh
```

не от `root`, скрипт попробует сделать:

```bash
sudo -E bash install.sh
```

Если `sudo` отсутствует, будет показана понятная ошибка.

## Ручной сценарий

Обычный путь установки должен идти через `bash install.sh`.
Но при необходимости можно запускать внутренние команды напрямую:

```bash
python3 -m install --help
python3 -m install init --non-interactive --set DOMAIN=example.com --set REALITY_DOMAIN=real.example.com
python3 -m install ensure-layout
python3 -m install prepare-host
python3 -m install seed-xui-db
```

## Что уже закрыто по сравнению с ранними версиями

- убран root `docker-compose.yml`
- убран root `install.py`
- `bootstrap` влит в `install`
- старый `sub2sing-box` переименован в `subconverter`
- сервис внутри compose переименован в `conv`
- сеть вынесена в внешний `proxy-net`
- ранние падения на `python3-venv` закрыты
- fallback на `docker-compose` для Debian закрыт
- installer UI стал подробнее

## Ограничения и честные замечания

- `sessionMaxAge=30` выставляется на уровне backend settings, но upstream UI сейчас показывает минимум `60`. Если потом сохранять это поле вручную через веб-интерфейс, оно может быть возвращено к `60`.
- Основной сценарий рассчитан именно на свежую VPS. Для уже “грязного” сервера результат может зависеть от текущего состояния Docker, `ufw`, занятых портов и DNS.
