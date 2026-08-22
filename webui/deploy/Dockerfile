# nginx:alpine with njs module for JSON directory listing API
FROM nginx:1.27-alpine

# Copy nginx config
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Copy njs scripts
COPY nginx/njs/ /etc/nginx/njs/

# Ensure njs module is loaded (available in nginx:alpine)
# The load_module directive in nginx.conf handles this

# 等待控制面启动时自动生成的 TOFU 证书（/etc/nginx/certs/server.crt）就绪后再起 nginx：
# compose 不保证容器启动顺序，缺证书时 nginx 会立即退出；等待循环保证首次 up 也能成功
CMD ["sh", "-c", "while [ ! -f /etc/nginx/certs/server.crt ]; do sleep 1; done; exec /docker-entrypoint.sh nginx -g 'daemon off;'"]
