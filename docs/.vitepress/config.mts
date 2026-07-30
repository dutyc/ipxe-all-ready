import { defineConfig } from 'vitepress'

export default defineConfig({
  // 开启 Clean URLs，去掉 .html 后缀
  title: 'Docs | iPXE-All-Ready',
  description: 'All is truly All. Ready is truly Ready.',
  head: [
    // 如果你使用的是 .ico 格式
    ['link', { rel: 'icon', type: 'image/png', href: '/logo1.png' }],
  ],
  cleanUrls: true,


  locales: {
    root: {
      label: 'English',
      lang: 'en',
      themeConfig: {
        nav: [
          { text: 'Home', link: '/' },
          { text: 'Guide', link: '/guide/preface' } // 导航栏默认指向指南的第一页(前言)
        ],
        sidebar: [
          {
            text: 'Guide',
            items: [
              { text: 'Preface', link: '/guide/preface' }, // 新增前言链接
              { text: 'Ch1: Architecture & Core Link', link: '/guide/architecture' },
              { text: 'Ch2: Windows 11 E2E Deployment', link: '/guide/windows-11' }
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
          { text: '实战指南', link: '/zh/guide/preface' } // 导航栏默认指向指南的第一页(前言)
        ],
        sidebar: [
          {
            text: '实战指南',
            items: [
              { text: '前言', link: '/zh/guide/preface' }, 
              { text: '第一章：架构设计与核心链路', link: '/zh/guide/architecture' },
              { text: '第二章: Windows 11 24H2 无盘系统全流程实战', link: '/zh/guide/windows-11' },
              { text: '第三章：Debian 12 无盘部署全流程', link: '/zh/guide/debian-12' },
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