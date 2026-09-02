// kurrent —— Kurrent 控制面 CLI（kubectl 同构，2026-08-31）。
// 零第三方依赖（net/http + encoding/json），go build 出单二进制。
//
// 全局选项可用环境变量 KURRENT_CP_URL / KURRENT_CP_TOKEN 兜底。
package main

import (
	"flag"
	"fmt"
	"os"
)

var (
	flagServer string
	flagToken  string
)

func fatal(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "kurrent: "+format+"\n", args...)
	os.Exit(1)
}

const usageText = `kurrent —— Kurrent 控制面 CLI（kubectl 同构，2026-08-31）

用法：
  kurrent [--server URL] [--token T] <group> <verb> [args]

全局选项（缺省读环境变量 KURRENT_CP_URL / KURRENT_CP_TOKEN）：
  --server  控制面 API 根（默认 http://127.0.0.1:4839；
            经 nginx 入口则传 https://<host>/api/cp）
  --token   控制面 Bearer token（WebUI 设置页可查）

命令组：
  agents list [--no-live] [-o table|json]    列出 Agent（含存活探测）
  agents get <id>                             查看单个 Agent
  agents add <id> --base-url URL [--role disk,cd] [--storager-ip IP] [--tags a,b] [--disabled]
  agents edit <id> --base-url URL [...]       更新 Agent（全量覆盖，参数同 add）
  agents remove <id>                          删除 Agent 台账（含母盘标签）
  agents probe --base-url URL                 探测 Agent 能力（不落盘）
  token create [--cp-url URL]                签发集群级通用 bootstrap token（kubeadm token
                                              create 同构：不绑节点，TTL 内可复用；输出带地址的
                                              join 命令——--cp-url 或从 --server 推导）
  config print init-defaults|node-defaults   输出声明模板（kubeadm config print 同构；
                                              重定向为 control_plane/kurrent.yaml 或
                                              storager/kurrent.yaml 后编辑）
  init [--config PATH] [--dir PATH]          控制面初始化：校验声明并收敛启动控制面
                                              （默认读 control_plane/kurrent.yaml，kubeadm
                                              init 同构；--config 指定其他声明文件则应用之）
  join <cp-url> [--config PATH] [--token T] [--dir PATH]
                                              节点侧加入（kubeadm join <endpoint> 同构）：
                                              声明 kurrent.yaml 缺失自动生成、已存在则读入并
                                              同步地址，收敛启动 agent（幂等可重跑）
  workers list | workers get <id>             Worker 台账（只读）
  ops list [--limit N] [-o table|json]        操作审计日志（只读）
`

func main() {
	fs := flag.NewFlagSet("kurrent", flag.ExitOnError)
	fs.StringVar(&flagServer, "server", os.Getenv("KURRENT_CP_URL"), "控制面 API 根")
	fs.StringVar(&flagToken, "token", os.Getenv("KURRENT_CP_TOKEN"), "控制面 Bearer token")
	fs.Parse(os.Args[1:])

	args := fs.Args()
	if len(args) == 0 || args[0] == "help" || args[0] == "-h" {
		fmt.Print(usageText)
		return
	}
	switch args[0] {
	case "agents":
		cmdAgents(args[1:])
	case "token":
		cmdToken(args[1:])
	case "config":
		cmdConfig(args[1:])
	case "init":
		cmdInit(args[1:])
	case "join":
		cmdJoin(args[1:])
	case "workers":
		cmdWorkers(args[1:])
	case "ops":
		cmdOps(args[1:])
	default:
		fatal("unknown command group: %s（help 查看用法）", args[0])
	}
}
