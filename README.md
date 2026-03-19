# 3XUI V1

Быстрая установка `3x-ui` на чистую VPS с Debian 12 или Debian 13.

## Быстрый старт

Можно запускать:

- от `root`
- от пользователя с `sudo`

Если `install.sh` запущен не от `root`, он сам попробует перезапуститься через `sudo`.

```bash
apt-get update
apt-get install -y git
git clone https://github.com/denash-git/3xui ~/3xui
cd ~/3xui
bash install.sh
```

Если нужен SSH-клон:

```bash
git clone git@github.com:denash-git/3xui.git ~/3xui
cd ~/3xui
bash install.sh
```

## Что делает установщик

- спрашивает основной домен, REALITY-домен и timezone
- ставит системные зависимости
- поднимает Docker и Compose
- настраивает `ufw`
- получает TLS-сертификат через `certbot`
- генерирует `instance.env`
- рендерит nginx, клиентскую страницу и fake-site
- поднимает `xui`, `conv`, `nginx`
- настраивает панель `3x-ui` и базовые inbound'ы
- после успешной установки удаляет install-time файлы с VPS

## Полная документация

[docs/README.md](/d:/WORK/3XUI/docs/README.md)
