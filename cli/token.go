// token 子命令：签发集群级通用引导凭据（kubeadm token create 同构）。
// 不带任何节点信息（kubeadm token create 不绑节点）：节点名由 join 自决
// （缺省取宿主机名）+ enroll 自动登记；TTL 内可被多次 enroll 复用。
// nvmet-host 组件凭据不在此签发：agent enroll 上报 backend=nvmet 时控制面
// 派生随响应下发（能力上报驱动，签发不预知后端）。
package main

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
)

type tokenResp struct {
	Token     string   `json:"token"`
	ExpiresAt string   `json:"expires_at"`
	Usage     []string `json:"usage"`
}

func cmdToken(args []string) {
	if len(args) < 1 || args[0] != "create" {
		fatal("用法: kurrent token create [--cp-url URL]\n" +
			"      （kubeadm token create 同构：集群级通用引导凭据，不绑节点，TTL 内可复用；\n" +
			"      --cp-url 指定节点侧可达的控制面 HTTPS 入口以输出可直接粘贴的 join 命令，\n" +
			"      缺省按 --server 主机推导 https://<host>）")
	}
	p := parseArgs(args[1:])
	var out tokenResp
	if err := json.Unmarshal(api("POST", "/pki/tokens", nil), &out); err != nil {
		fatal("解析 token 响应: %v", err)
	}
	fmt.Printf("bootstrap token: %s（expires %s，TTL 内可被多次 enroll 复用）\n",
		out.Token, out.ExpiresAt)
	fmt.Printf("\n# 存储节点上执行（kubeadm join 同构；命令已携带控制面地址，节点执行即自动生成/更新声明）：\n")
	fmt.Printf("kurrent join %s --token %s\n", joinCpURL(p.opt("cp-url", "")), out.Token)
	fmt.Printf("# 加入后验证：kurrent agents list（或 WebUI「Agent 列表」health=ok）\n")
}

// joinCpURL 推导节点侧控制面入口（kubeadm token create --print-join-command 同构：
// 输出带地址的 join 命令）：显式 --cp-url 优先，否则按 --server 主机推 https://<host>。
func joinCpURL(explicit string) string {
	if explicit != "" {
		return strings.TrimRight(explicit, "/")
	}
	server := strings.TrimRight(flagServer, "/")
	if server == "" {
		return "https://127.0.0.1"
	}
	u, err := url.Parse(server)
	if err != nil || u.Host == "" {
		return "https://127.0.0.1"
	}
	return "https://" + u.Hostname()
}
