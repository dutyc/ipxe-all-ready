// 控制面 HTTP 客户端：Bearer 鉴权 + JSON，非 2xx 打印 detail 后退出。
package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"
)

// api 向控制面发请求并返回响应体；非 2xx 时打印错误并退出进程。
func api(method, path string, body any) []byte {
	server := strings.TrimRight(flagServer, "/")
	if server == "" {
		server = "http://127.0.0.1:4839"
	}
	var rd io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			fatal("encode request body: %v", err)
		}
		rd = bytes.NewReader(data)
	}
	req, err := http.NewRequest(method, server+path, rd)
	if err != nil {
		fatal("build request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if flagToken != "" {
		req.Header.Set("Authorization", "Bearer "+flagToken)
	}
	resp, err := (&http.Client{Timeout: 15 * time.Second}).Do(req)
	if err != nil {
		fatal("connect %s: %v", server, err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		fatal("%s %s -> HTTP %d: %s", method, path, resp.StatusCode, detailOf(data))
	}
	return data
}

// detailOf 从 FastAPI 错误响应中提取人类可读的 detail。
func detailOf(data []byte) string {
	var m map[string]any
	if json.Unmarshal(data, &m) == nil {
		switch d := m["detail"].(type) {
		case string:
			return d
		case map[string]any:
			if s, ok := d["error"].(string); ok {
				return s
			}
			if b, err := json.Marshal(d); err == nil {
				return string(b)
			}
		}
	}
	return strings.TrimSpace(string(data))
}
