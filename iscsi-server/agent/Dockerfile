FROM python:3.11-slim

# 时区数据：日志时间戳跟随 TZ 环境变量（/etc/localtime 挂载失效时的兜底）
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt .
# pip 走阿里云镜像加速（国内网络环境安装依赖更快）
RUN pip install --no-cache-dir \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com \
        -r requirements.txt

COPY app ./app

# 前台跑 HTTP 服务，监听 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]