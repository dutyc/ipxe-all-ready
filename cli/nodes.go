// nodes 子命令：bootstrap token 签发 + 输出节点侧一键加入命令（kubeadm token create 同构）。
package main

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
)

type tokenResp struct {
	AgentID    string `json:"agent_id"`
	Component  string `json:"component"`
	Token      string `json:"token"`
	ExpiresAt  string `json:"expires_at"`
}

func cmdNodes(args []string) {
	if len(args) < 1 || args[0] != "token" {
		fatal("用法: kurrent nodes token <agent-id> [--nvmet] [--cp-url URL]")
	}
	p := parseArgs(args[1:])
	agentID := firstPos(p)
	if agentID == "" {
		fatal("用法: kurrent nodes token <agent-id> [--nvmet] [--cp-url URL]")
	}

	agentTok := issueToken(agentID, "agent")
	fmt.Printf("agent 组件 token:     %s（expires %s，enroll 后即废）\n", agentTok.Token, agentTok.ExpiresAt)

	join := []string{"kurrent", "join", joinCpURL(p.opt("cp-url", "")), agentTok.Token, agentID}
	if p.has("nvmet") {
		nvmetTok := issueToken(agentID, "nvmet-host")
		fmt.Printf("nvmet-host 组件 token: %s（expires %s，enroll 后即废）\n", nvmetTok.Token, nvmetTok.ExpiresAt)
		join = append(join, "--nvmet-token", nvmetTok.Token)
	}
	fmt.Printf("\n# 存储节点上执行（kubeadm join 同构，一条命令加入；无 Go 环境可用 ./kurrent-join.sh 等价替代）：\n%s\n", strings.Join(join, " "))
	fmt.Printf("# 加入后验证：kurrent agents list（或 WebUI「Agent 列表」health=ok）\n")
}

// issueToken 调控制面签发一次性 bootstrap token。
func issueToken(agentID, component string) tokenResp {
	path := "/agents/" + agentID + "/bootstrap-token?component=" + component
	var out tokenResp
	if err := json.Unmarshal(api("POST", path, nil), &out); err != nil {
		fatal("解析 token 响应: %v", err)
	}
	return out
}

// joinCpURL 推导节点侧控制面入口：显式指定优先，否则按 --server 主机推 https://<host>。
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
