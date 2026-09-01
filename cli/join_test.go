// kurrent join 沙盒测试：临时仓库 + fake docker，验证 .env 幂等 upsert、默认值推导与 compose 调用。
package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const fakeDocker = `#!/usr/bin/env bash
echo "FAKE-DOCKER $(pwd) $*" >> "${FAKE_DOCKER_LOG}"
`

// newFakeRepo 建临时仓库骨架（storager/{nvmeof,iscsi} + fake docker，PATH 注入）。
func newFakeRepo(t *testing.T) (repo, storager, logFile string) {
	t.Helper()
	repo = t.TempDir()
	storager = filepath.Join(repo, "storager")
	for _, d := range []string{"nvmeof", "iscsi"} {
		if err := os.MkdirAll(filepath.Join(storager, d), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	bin := filepath.Join(repo, "bin")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	logFile = filepath.Join(repo, "docker.log")
	if err := os.WriteFile(filepath.Join(bin, "docker"), []byte(fakeDocker), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("FAKE_DOCKER_LOG", logFile)
	return repo, storager, logFile
}

// envValues 返回 .env 中某键的全部值（末位为最新）。
func envValues(t *testing.T, envFile, key string) []string {
	t.Helper()
	data, err := os.ReadFile(envFile)
	if err != nil {
		t.Fatal(err)
	}
	prefix := key + "="
	var vals []string
	for _, l := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(l, prefix) {
			vals = append(vals, strings.TrimPrefix(l, prefix))
		}
	}
	return vals
}

func TestJoinBasic(t *testing.T) {
	_, storager, logFile := newFakeRepo(t)
	err := joinRun(joinOpts{
		dir:          storager,
		cpURL:        "https://192.168.1.10",
		token:        "abc123.def456",
		agentID:      "storage-01",
		nvmetToken:   "789abc.def012",
		advertiseURL: "https://192.168.1.50:4840",
	})
	if err != nil {
		t.Fatal(err)
	}
	envFile := filepath.Join(storager, ".env")
	for key, want := range map[string]string{
		"KURRENT_AGENT_ID":             "storage-01",
		"KURRENT_BOOTSTRAP_TOKEN":      "abc123.def456",
		"KURRENT_CP_ENROLL_URL":        "https://192.168.1.10",
		"KURRENT_ADVERTISE_URL":        "https://192.168.1.50:4840",
		"KURRENT_BACKEND":              "nvmet",
		"KURRENT_BOOTSTRAP_TOKEN_NVMET": "789abc.def012",
	} {
		if got := envValues(t, envFile, key); len(got) != 1 || got[0] != want {
			t.Errorf("%s = %v, want %q", key, got, want)
		}
	}
	// 证书宿主目录按 agent_id 隔离
	got := envValues(t, envFile, "KURRENT_AGENT_PKI_HOST")[0]
	if !strings.HasSuffix(got, "control_plane/state/pki/components/agent-storage-01") {
		t.Errorf("KURRENT_AGENT_PKI_HOST = %s, want suffix components/agent-storage-01", got)
	}
	got = envValues(t, envFile, "KURRENT_NVMET_PKI_HOST")[0]
	if !strings.HasSuffix(got, "control_plane/state/pki/components/nvmet-storage-01") {
		t.Errorf("KURRENT_NVMET_PKI_HOST = %s, want suffix components/nvmet-storage-01", got)
	}
	// nvmet 后端 → storager/nvmeof 下执行 compose
	logData, err := os.ReadFile(logFile)
	if err != nil {
		t.Fatal(err)
	}
	log := string(logData)
	if !strings.Contains(log, "FAKE-DOCKER "+storager+"/nvmeof compose --env-file ../.env up -d") {
		t.Errorf("docker 调用不符: %s", log)
	}
}

func TestJoinIdempotentBackendInherit(t *testing.T) {
	_, storager, logFile := newFakeRepo(t)
	envFile := filepath.Join(storager, ".env")
	// 预置 lio 后端（模拟既有 iSCSI 部署）
	if err := os.WriteFile(envFile, []byte("KURRENT_BACKEND=lio\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := joinRun(joinOpts{dir: storager, cpURL: "https://cp2", token: "aaa.111", agentID: "storage-02"}); err != nil {
		t.Fatal(err)
	}
	// 后端沿用现有 .env，advertise 默认推导 https://<cp-host>:4840
	if got := envValues(t, envFile, "KURRENT_BACKEND"); len(got) != 1 || got[0] != "lio" {
		t.Errorf("KURRENT_BACKEND = %v, want [lio]", got)
	}
	if got := envValues(t, envFile, "KURRENT_ADVERTISE_URL"); len(got) != 1 || got[0] != "https://cp2:4840" {
		t.Errorf("KURRENT_ADVERTISE_URL = %v, want [https://cp2:4840]", got)
	}
	// 换 agent_id 重跑（幂等 upsert：键唯一，不堆积）
	if err := joinRun(joinOpts{dir: storager, cpURL: "https://cp2", token: "bbb.222", agentID: "storage-03"}); err != nil {
		t.Fatal(err)
	}
	if got := envValues(t, envFile, "KURRENT_AGENT_ID"); len(got) != 1 || got[0] != "storage-03" {
		t.Errorf("KURRENT_AGENT_ID = %v, want [storage-03]（幂等）", got)
	}
	if got := envValues(t, envFile, "KURRENT_BOOTSTRAP_TOKEN"); len(got) != 1 || got[0] != "bbb.222" {
		t.Errorf("KURRENT_BOOTSTRAP_TOKEN = %v, want [bbb.222]", got)
	}
	// lio 后端 → storager/iscsi 下执行 compose（两次调用都在）
	logData, err := os.ReadFile(logFile)
	if err != nil {
		t.Fatal(err)
	}
	log := string(logData)
	if n := strings.Count(log, "FAKE-DOCKER "+storager+"/iscsi compose --env-file ../.env up -d"); n != 2 {
		t.Errorf("iscsi compose 调用次数 = %d, want 2\n%s", n, log)
	}
}

func TestJoinInvalidBackend(t *testing.T) {
	_, storager, _ := newFakeRepo(t)
	err := joinRun(joinOpts{dir: storager, cpURL: "https://cp", token: "t", agentID: "a", backend: "hacker"})
	if err == nil || !strings.Contains(err.Error(), "invalid backend") {
		t.Fatalf("err = %v, want invalid backend", err)
	}
}

func TestResolveStoragerDir(t *testing.T) {
	repo, storager, _ := newFakeRepo(t)
	// --dir 显式
	if got, err := resolveStoragerDir(storager); err != nil || got != storager {
		t.Fatalf("resolveStoragerDir(%s) = %q, %v", storager, got, err)
	}
	// 仓库根（cwd 下存在 storager/）
	t.Chdir(repo)
	if got, err := resolveStoragerDir(""); err != nil || got != storager {
		t.Fatalf("仓库根解析 = %q, %v, want %q", got, err, storager)
	}
	// 已位于 storager 内（cwd 下存在 nvmeof/）
	t.Chdir(storager)
	if got, err := resolveStoragerDir(""); err != nil || got != storager {
		t.Fatalf("storager 内解析 = %q, %v, want %q", got, err, storager)
	}
	// 找不到
	t.Chdir(t.TempDir())
	if _, err := resolveStoragerDir(""); err == nil {
		t.Fatal("期望找不到 storager 目录报错")
	}
}
