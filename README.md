# 3XUI V1

Быстрая установка на чистую VPS с Debian 12 или Debian 13.

## Быстрый старт

Запускать можно от `root` или от пользователя с `sudo`.
Если `install.sh` запущен не от `root`, он сам попробует перезапуститься через `sudo`.

```bash
apt-get update
apt-get install -y git
git clone https://github.com/denash-git/3xui ~/3xui
cd ~/3xui
bash install.sh
```

Если удобнее SSH-клон:

```bash
git clone git@github.com:denash-git/3xui.git ~/3xui
cd ~/3xui
bash install.sh
```

## Что делает установщик

- спрашивает основной домен, REALITY-домен и timezone
- сам ставит системные зависимости
- поднимает Docker и Compose
- настраивает `ufw` и открывает `22`, `80`, `443`
- создаёт или использует внешний Docker network `proxy-net`
- получает TLS-сертификат через `certbot`
- генерирует `instance.env`
- рендерит nginx, клиентскую страницу и fake-site
- поднимает `xui`, `conv`, `nginx`
- настраивает панель `3x-ui`, базовые inbound'ы и `sessionMaxAge=30`
- включает тёмную тему панели через nginx-injection hack по умолчанию
- после успешной установки удаляет с VPS install-time файлы и оставляет только runtime-дерево

## Что останется на VPS после успешной установки

- `instance.env`
- `nginx/`
- `xui/`
- `subconverter/`
- `web/`

Служебные каталоги установщика, документация, шаблоны, `.venv` и временные файлы будут удалены.

## Важно

- Поддерживаемый сценарий сейчас: свежая Debian 12/13 VPS.
- Установщик заранее проверяет:
  - права `root`
  - доступность `apt-get`
  - свободны ли порты `80` и `443`
  - корректно ли выглядит сеть `proxy-net`
  - резолвится ли основной домен
- Если с проверками что-то не так, установка останавливается с понятной ошибкой.

## Документация

Полная документация: [docs/README.md](/d:/WORK/3XUI/docs/README.md)
