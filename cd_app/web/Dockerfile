# Static web image. The Flutter web bundle is built locally and copied into
# ./html before building this image (see cd_app/deploy/README.md).
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY html/ /usr/share/nginx/html/
