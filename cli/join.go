// join 子命令：存储节点一键加入控制面（kubeadm join 同构，2026-08-31）。
// 幂等更新 storager/.env 后启动后端编排（nvmet: storager/nvmeof；stgt|lio: storager/iscsi）。
// 与 storager/kurrent-join.sh 行为一致；无 Go 环境时可用该脚本等价替代。
package main

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

func cmdJoin(args []string) {
	p := parseArgs(args)
	if len(p.pos) < 3 {
		fatal("用法: kurrent join <cp-url> <bootstrap-token> <agent-id> " +
			"[--nvmet-token T] [--advertise-url URL] [--backend nvmet|stgt|lio] [--dir PATH]")
	}
	dir, err := resolveStoragerDir(p.opt("dir", ""))
	if err != nil {
		fatal("%v", err)
	}
	err = joinRun(joinOpts{
		dir:          dir,
		cpURL:        p.pos[0],
		token:        p.pos[1],
		agentID:      p.pos[2],
		nvmetToken:   p.opt("nvmet-token", ""),
		advertiseURL: p.opt("advertise-url", ""),
		backend:      p.opt("backend", ""),
	})
	if err != nil {
		fatal("%v", err)
	}
}

type joinOpts struct {
	dir          string // storager 目录
	cpURL        string
	token        string
	agentID      string
	nvmetToken   string
	advertiseURL string
	backend      string
}

// resolveStoragerDir 定位 storager 目录：--dir 优先；否则 cwd 下 storager/；cwd 已是 storager 时用 cwd。
func resolveStoragerDir(explicit string) (string, error) {
	if explicit != "" {
		abs, err := filepath.Abs(explicit)
		if err != nil {
			return "", fmt.Errorf("解析 --dir: %w", err)
		}
		return abs, nil
	}
	cwd, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("获取当前目录: %w", err)
	}
	if fi, err := os.Stat(filepath.Join(cwd, "storager")); err == nil && fi.IsDir() {
		return filepath.Join(cwd, "storager"), nil
	}
	if _, err := os.Stat(filepath.Join(cwd, "nvmeof")); err == nil {
		return cwd, nil // 已位于 storager 内
	}
	return "", fmt.Errorf("未找到 storager 目录（请在仓库根运行，或用 --dir 指定）")
}

var cpHostRe = regexp.MustCompile(`https?://([^/:]+)`)

// joinRun 幂等写 .env 并拉起后端编排（测试直接调用，不经 cmdJoin）。
func joinRun(o joinOpts) error {
	cpURL := strings.TrimRight(o.cpURL, "/")
	m := cpHostRe.FindStringSubmatch(cpURL)
	if len(m) < 2 {
		return fmt.Errorf("无法从 cp-url 解析主机名: %s", o.cpURL)
	}

	advertise := strings.TrimSpace(o.advertiseURL)
	if advertise == "" {
		advertise = "https://" + m[1] + ":4840"
	}
	backend := strings.TrimSpace(o.backend)
	if backend == "" {
		backend = envValue(filepath.Join(o.dir, ".env"), "KURRENT_BACKEND") // 后端沿用现有部署
	}
	if backend == "" {
		backend = "nvmet"
	}
	var composeDir string
	switch backend {
	case "nvmet":
		composeDir = filepath.Join(o.dir, "nvmeof")
	case "stgt", "lio":
		composeDir = filepath.Join(o.dir, "iscsi")
	default:
		return fmt.Errorf("invalid backend: %s (nvmet|stgt|lio)", backend)
	}

	envFile := filepath.Join(o.dir, ".env")
	projectRoot := filepath.Dir(o.dir)
	entries := []envEntry{
		{"KURRENT_AGENT_ID", o.agentID},
		{"KURRENT_BOOTSTRAP_TOKEN", o.token},
		{"KURRENT_CP_ENROLL_URL", cpURL},
		{"KURRENT_ADVERTISE_URL", advertise},
		{"KURRENT_BACKEND", backend},
		{"KURRENT_AGENT_PKI_HOST", filepath.Join(projectRoot, "control_plane/state/pki/components/agent-"+o.agentID)},
	}
	if o.nvmetToken != "" {
		entries = append(entries,
			envEntry{"KURRENT_BOOTSTRAP_TOKEN_NVMET", o.nvmetToken},
			envEntry{"KURRENT_NVMET_PKI_HOST", filepath.Join(projectRoot, "control_plane/state/pki/components/nvmet-"+o.agentID)},
		)
	}
	if err := upsertEnv(envFile, entries); err != nil {
		return err
	}

	fmt.Printf("==> kurrent join: agent=%s backend=%s cp=%s\n", o.agentID, backend, cpURL)
	fmt.Printf("==> kurrent join: starting %s (compose --env-file ../.env)\n", composeDir)
	cmd := exec.Command("docker", "compose", "--env-file", "../.env", "up", "-d")
	cmd.Dir = composeDir
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("docker compose 启动失败: %w", err)
	}
	fmt.Println("==> kurrent join: done. 容器首次启动会自动引导证书；")
	fmt.Println("    控制面侧验证: kurrent agents list（或 WebUI「Agent 列表」看 health=ok）")
	return nil
}

type envEntry struct{ key, value string }

// envValue 读 .env 中最后一个匹配键的值（无则空）。
func envValue(path, key string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	prefix := key + "="
	val := ""
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if line := sc.Text(); strings.HasPrefix(line, prefix) {
			val = strings.TrimPrefix(line, prefix)
		}
	}
	return val
}

// upsertEnv 幂等更新 .env：删除所有既有匹配键的行再追加（键唯一，重复 join 不堆积）。
func upsertEnv(path string, entries []envEntry) error {
	var lines []string
	if data, err := os.ReadFile(path); err == nil {
		drop := map[string]bool{}
		for _, e := range entries {
			drop[e.key] = true
		}
		for _, line := range strings.Split(string(data), "\n") {
			key := line
			if i := strings.IndexByte(key, '='); i >= 0 {
				key = key[:i]
			}
			if !drop[key] {
				lines = append(lines, line)
			}
		}
	}
	for len(lines) > 0 && lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	for _, e := range entries {
		lines = append(lines, e.key+"="+e.value)
	}
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o644); err != nil {
		return fmt.Errorf("写入 %s: %w", path, err)
	}
	return nil
}
