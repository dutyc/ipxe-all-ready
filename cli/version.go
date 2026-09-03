// 版本号：发版构建时经 go build -ldflags "-X main.version=vX.Y.Z" 注入；
// 日常构建未注入时显示 dev。
package main

import "fmt"

var version = "dev"

func cmdVersion(args []string) {
	if len(args) > 0 {
		fmt.Println("用法: kurrent version")
		return
	}
	fmt.Printf("kurrent %s\n", version)
}
