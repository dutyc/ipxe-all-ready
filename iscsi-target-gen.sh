#!/bin/bash
set -e

# 容器配置
CONTAINER_NAME="ipxe-iscsi"
DISK_DIR="/home/iscsi_img"

# 自定义基础IQN（格式：iqn.域名:自定义标识）
IQN_BASE="iqn.2026-07.com.controller"

# 默认访问控制策略（可修改为具体IP或CIDR）
DEFAULT_ACL="ALL"

# 检查容器状态
check_container() {
    if ! docker inspect --format='{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q 'true'; then
        echo "错误：容器 $CONTAINER_NAME 未运行或不存在"
        exit 1
    fi
}

# 获取镜像文件列表 (支持 .img 和 .iso)
get_image_files() {
    # 使用 || true 防止在没有匹配文件时因 set -e 导致脚本退出
    docker exec "$CONTAINER_NAME" ls "$DISK_DIR" 2>/dev/null | grep -Ei '\.(img|iso)$' || true
}

# 创建iSCSI Target
create_iscsi_target() {
    local tid=$1
    local filename=$2
    
    # 获取文件扩展名
    local ext="${filename##*.}"
    local name_suffix
    
    # 根据文件类型生成不同的 IQN 后缀，防止名称冲突
    if [[ "${ext,,}" == "iso" ]]; then
        # ISO 文件保留完整文件名（包含 .iso）
        name_suffix="${filename}"
    else
        # IMG 等其他文件去除扩展名
        name_suffix="${filename%.*}"
    fi
    
    # 生成完整IQN
    local iqn="${IQN_BASE}:${name_suffix}"
    
    # 创建Target
    echo "创建 Target: $iqn (TID=$tid, 类型: ${ext^^})"
    docker exec "$CONTAINER_NAME" tgtadm \
        --lld iscsi \
        --mode target \
        --op new \
        --tid "$tid" \
        --targetname "$iqn"

    # 创建LUN
    local disk_path="${DISK_DIR}/${filename}"
    echo "  创建 LUN 1 -> $disk_path"
    
    # 根据文件类型构建不同的 LUN 创建命令
    if [[ "${ext,,}" == "iso" ]]; then
        # ISO 文件：指定设备类型为 cd (光驱)，移除无效的 bstype 参数
        docker exec "$CONTAINER_NAME" tgtadm \
            --lld iscsi \
            --mode logicalunit \
            --op new \
            --tid "$tid" \
            --lun 1 \
            --backing-store "$disk_path" \
            --device-type cd
    else
        # IMG 文件：使用默认硬盘类型
        docker exec "$CONTAINER_NAME" tgtadm \
            --lld iscsi \
            --mode logicalunit \
            --op new \
            --tid "$tid" \
            --lun 1 \
            --backing-store "$disk_path"
    fi

    # 配置访问控制
    echo "  绑定访问策略 -> $DEFAULT_ACL"
    docker exec "$CONTAINER_NAME" tgtadm \
        --lld iscsi \
        --mode target \
        --op bind \
        --tid "$tid" \
        --initiator-address "$DEFAULT_ACL"
    
    echo ""
}

# 主流程
check_container

# 获取镜像文件列表
files=()
while IFS= read -r line; do
    [ -n "$line" ] && files+=("$line")
done < <(get_image_files)

if [ ${#files[@]} -eq 0 ]; then
    echo "警告：未在 $DISK_DIR 目录下找到任何 .img 或 .iso 镜像文件"
    exit 1
fi

echo "发现以下镜像文件："
printf '  %s\n' "${files[@]}"
echo "使用基础IQN模板: ${IQN_BASE}:<文件名/后缀>"
echo ""

# 为每个镜像文件创建Target
tid=1
for file in "${files[@]}"; do
    create_iscsi_target "$tid" "$file"
    tid=$((tid + 1))
done

# 显示最终配置
echo "显示当前所有 Target 配置:"
docker exec "$CONTAINER_NAME" tgtadm --lld iscsi --mode target --op show