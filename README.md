# TransitHub v2

Быстрая установка proxy platform на чистую VPS с Debian 12 или Debian 13.

## Быстрый старт

Одной строкой:

```bash
sudo bash <(wget -qO- https://raw.githubusercontent.com/denash-git/TransitHub/main/bootstrap.sh)
```

Тестовый прогон без production rate limit Let's Encrypt:

```bash
CERTBOT_STAGING=true sudo bash <(wget -qO- https://raw.githubusercontent.com/denash-git/TransitHub/main/bootstrap.sh)
```

Или обычным clone-сценарием:

Можно запускать:

- от `root`
- от пользователя с `sudo`

Если `install.sh` запущен не от `root`, он сам попробует перезапуститься через `sudo`.

```bash
apt-get update
apt-get install -y git
git clone https://github.com/denash-git/TransitHub.git ~/TransitHub
cd ~/TransitHub
bash install.sh
```

## Что делает установщик

- спрашивает основной домен, REALITY-домен, host Telegram-прокси, FakeTLS-домен и timezone
- ставит системные зависимости
- поднимает Docker и Compose
- настраивает `ufw`
- получает TLS-сертификат через `certbot`
- включает автоматическое продление TLS-сертификата через `systemd timer`
- поддерживает `CERTBOT_STAGING=true` для безопасных тестовых прогонов
- генерирует `instance.env`
- рендерит nginx, клиентскую страницу и fake-site
- поднимает `xui`, `conv`, `nginx` и опционально `tgproxy`
- настраивает панель `3x-ui` и базовые inbound'ы
- после успешной установки удаляет install-time файлы с VPS

## Полная документация

[docs/README.md](docs/README.md)
