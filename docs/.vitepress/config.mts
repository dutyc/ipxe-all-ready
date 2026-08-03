import { defineConfig } from 'vitepress'

export default defineConfig({
  // 开启 Clean URLs，去掉 .html 后缀
  title: 'iPXE-All-Ready',
  description: 'All is truly All. Ready is truly Ready.',
  head: [
    ['link', { rel: 'icon', type: 'image/png', href: '/logo.png' }],
  ],
  cleanUrls: true,


  locales: {
    root: {
      label: 'English',
      lang: 'en',
      themeConfig: {
        nav: [
          { text: 'Home', link: '/' },
          { text: 'Exploration', link: '/guide/preface' },
          { text: 'Quick Deploy', link: '/guide/quick-deploy/environment-deploy' } // 导航栏指向各专栏首页
        ],
        sidebar: [
          {
            text: 'Exploration',
            collapsed: false,
            items: [
              { text: 'Foreword', link: '/guide/preface' },
              { text: 'Ch1: Architecture & Core Link', link: '/guide/architecture' },
              { text: 'Ch2: Windows 11 E2E Deployment', link: '/guide/windows-11' },
              { text: 'Ch3: Debian 12 Diskless Deployment', link: '/guide/debian-12' },
              { text: 'Ch4: Debian-family iBFT Boot', link: '/guide/debian-12-ibft' },
              { text: 'Control Plane Capabilities', link: '/guide/control-plane' },
              { text: 'Barriers We Have Broken Through', link: '/guide/barriers' },
            ]
          },
          {
            text: 'Quick Deploy',
            collapsed: false,
            items: [
              { text: 'Environment Setup', link: '/guide/quick-deploy/environment-deploy' },
              { text: 'Windows Master Image (Clone)', link: '/guide/quick-deploy/windows-quick-deploy' },
              { text: 'Debian-family Master Image (Clone)', link: '/guide/quick-deploy/debian-quick-deploy' },
            ]
          }
        ]
      }
    },
    zh: {
      label: '中文',
      lang: 'zh-CN',
      link: '/zh/',
      themeConfig: {
        nav: [
          { text: '首页', link: '/zh/' },
          { text: '原理探索', link: '/zh/guide/preface' },
          { text: '快速部署', link: '/zh/guide/quick-deploy/environment-deploy' } // 导航栏默认指向原理探索专栏首页(前言)
        ],
        sidebar: [
          {
            text: '原理探索',
            collapsed: false,
            items: [
              { text: '前言', link: '/zh/guide/preface' },
              { text: '第一章：架构设计与核心链路', link: '/zh/guide/exploration/architecture' },
              { text: '第二章: Windows 11 24H2 无盘系统全流程实战', link: '/zh/guide/exploration/windows-11' },
              { text: '第三章：Debian 12 无盘部署全流程', link: '/zh/guide/exploration/debian-12' },
              { text: '第四章：Debian 系 iBFT 无盘启动', link: '/zh/guide/exploration/debian-12-ibft' },
              { text: '控制面能力详解', link: '/zh/guide/exploration/control-plane' },
              { text: '我们已经攻克的壁垒', link: '/zh/guide/exploration/barriers' },
            ]
          },
          {
            text: '快速部署',
            collapsed: false,
            items: [
              { text: '项目环境部署', link: '/zh/guide/quick-deploy/environment-deploy' },
              { text: 'Windows 无盘快速部署（母盘克隆）', link: '/zh/guide/quick-deploy/windows-quick-deploy' },
              { text: 'Debian 系无盘快速部署（母盘克隆）', link: '/zh/guide/quick-deploy/debian-quick-deploy' },
            ]
          }
        ]
      }
    }
  },



  // 全局主题配置
  themeConfig: {
    // 右上角社交链接与搜索
    socialLinks: [
      { icon: 'github', link: 'https://github.com/dutyc/ipxe-all-ready' }
    ],
    search: {
      provider: 'local'
    },
    // 页面编辑链接 (方便未来社区提交 PR)
    editLink: {
      pattern: 'https://github.com/dutyc/ipxe-all-ready/edit/main/docs/:path',
      text: '在 GitHub 上编辑此页'
    }
  }
})