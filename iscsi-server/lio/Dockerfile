FROM debian:bookworm-slim

# 换阿里云源。bookworm 源在 deb822 格式的 debian.sources（URIs 字段），
# 老镜像才在 sources.list；只替换域名，协议和路径不动，两种格式都覆盖。
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
        targetcli-fb dbus ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*
