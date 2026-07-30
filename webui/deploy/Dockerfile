# nginx:alpine with njs module for JSON directory listing API
FROM nginx:1.27-alpine

# Copy nginx config
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Copy njs scripts
COPY nginx/njs/ /etc/nginx/njs/

# Ensure njs module is loaded (available in nginx:alpine)
# The load_module directive in nginx.conf handles this
