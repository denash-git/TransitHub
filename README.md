# TransitHub v2

TransitHub v2 разворачивает proxy platform на чистой VPS с Debian 12 или Debian 13.

## Что потребуется

- Debian 12 или Debian 13
- доступ `root` или пользователь с `sudo`
- свободные порты `80/tcp` и `443/tcp`
- домен панели, уже направленный на VPS
- если включается Telegram-прокси, его домен тоже должен резолвиться на VPS

## Быстрая установка

Одной строкой:

```bash
BRANCH="${TRANSITHUB_BRANCH:-main}"
bash <(wget -qO- "https://raw.githubusercontent.com/denash-git/TransitHub/${BRANCH}/bootstrap.sh")
```

или:

```bash
BRANCH="${TRANSITHUB_BRANCH:-main}"
bash <(curl -fsSL "https://raw.githubusercontent.com/denash-git/TransitHub/${BRANCH}/bootstrap.sh")
```

Или обычным clone-сценарием:

```bash
apt-get update
apt-get install -y git
TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
BRANCH="${TRANSITHUB_BRANCH:-main}"
git clone --branch "$BRANCH" https://github.com/denash-git/TransitHub.git "${TARGET_HOME}/TransitHub"
cd "${TARGET_HOME}/TransitHub"
bash install.sh
```

Если `install.sh` запущен не от `root`, скрипт сам попробует перезапуститься через `sudo`.

## Что спросит установщик

- `Main domain`
  Основной домен панели, клиентской страницы и подписок.
- `REALITY domain`
  Домен для REALITY.
- `Telegram proxy domain`
  Домен Telegram-прокси. Если ввести `-`, Telegram-прокси не будет поднят.
- `NetBird setup key`
  Опциональный setup key NetBird. Если оставить пустым или ввести `-`, NetBird не будет подключаться.
- `NetBird management URL`
  URL панели управления NetBird в формате `https://...`. Спрашивается только если задан setup key.
- `Timezone`
  Таймзона контейнеров. По умолчанию берётся текущая таймзона VPS.

## Что делает установка

- выполняет preflight-проверки хоста
- ставит системные пакеты, Docker и Compose
- настраивает `ufw`
- выпускает TLS-сертификат Let's Encrypt
- настраивает автоматическое продление сертификата через `systemd timer`
- генерирует runtime-конфиги
- поднимает `nginx`, `xui`, `conv` и опционально Telegram-прокси и NetBird
- настраивает `3x-ui` и базовые inbound'ы
- если включён NetBird, готовит хост для routing peer / exit node без смены default route на самой VPS

## Полезно знать

- по умолчанию используется боевой Let's Encrypt сертификат
- для тестового сертификата можно запустить:

```bash
BRANCH="${TRANSITHUB_BRANCH:-main}"
CERTBOT_STAGING=true bash <(wget -qO- "https://raw.githubusercontent.com/denash-git/TransitHub/${BRANCH}/bootstrap.sh")
```

или:

```bash
BRANCH="${TRANSITHUB_BRANCH:-main}"
CERTBOT_STAGING=true bash <(curl -fsSL "https://raw.githubusercontent.com/denash-git/TransitHub/${BRANCH}/bootstrap.sh")
```

- если время на VPS не синхронизировано, установщик покажет предупреждение, но продолжит работу
- если включён NetBird, контейнер поднимается в `host` network mode и получает внутренний интерфейс `wt0`, но default route самой VPS не меняется
- с `3x-ui` можно взаимодействовать и через CLI внутри контейнера:

```bash
XUI_CONTAINER="$(docker ps --format '{{.Names}}' | grep xui | head -n1)"
docker exec -it "$XUI_CONTAINER" /bin/sh
x-ui
```

- после установки локальное меню проекта доступно командой:

```bash
menu
```

- в `Services` доступны:
  `Backup Bundle` и `Restore Bundle`
- backup bundle сохраняется в `~/TransitHub/backup`
- restore берёт самый новый `backup-*.tar.gz` из той же папки и перед
  восстановлением автоматически создаёт `backup-rollback-*.tar.gz`

Если launcher ещё не установлен или нужно запустить файл напрямую:

```bash
TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
cd "${TARGET_HOME}/TransitHub"
python3 transithub-menu.py
```
