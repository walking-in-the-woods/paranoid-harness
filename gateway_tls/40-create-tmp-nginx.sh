#!/bin/sh
# Выполняется nginx:1.27.2-alpine entrypoint'ом из /docker-entrypoint.d/
# перед `nginx -g daemon off;`.
#
# Зачем: nginx создаёт temp-каталоги (client_body, proxy, fastcgi,
# uwsgi, scgi) через нерекурсивный mkdir(). Родительский каталог
# /tmp/nginx должен существовать до старта nginx, иначе он упадёт с
# "mkdir(...) failed (2: No such file or directory)".
#
# /tmp — tmpfs (см. docker-compose.yml), поэтому каталог нельзя
# создать на build-time: слой образа скрывается при монтировании.
#
# set -e заключён в subshell: nginx entrypoint source'ит все *.sh
# в текущем shell, и `set -e` без subshell утёк бы в остальные
# entrypoint-скрипты, меняя их поведение.

(
    set -e
    mkdir -p /tmp/nginx
    chown nginx:nginx /tmp/nginx
)
