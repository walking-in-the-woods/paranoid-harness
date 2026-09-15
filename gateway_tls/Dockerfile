FROM nginx:1.27.2-alpine

RUN rm /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/nginx.conf

# nginx:alpine entrypoint исполняет /docker-entrypoint.d/*.sh до старта.
# Создаём /tmp/nginx на runtime — build-time mkdir бесполезен (tmpfs).
COPY 40-create-tmp-nginx.sh /docker-entrypoint.d/40-create-tmp-nginx.sh
RUN chmod 0755 /docker-entrypoint.d/40-create-tmp-nginx.sh

EXPOSE 8443

# ENTRYPOINT/CMD наследуются от базового образа:
#   ENTRYPOINT /docker-entrypoint.sh
#   CMD        nginx -g "daemon off;"
