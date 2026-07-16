import { defineConfig } from 'vitepress'

export default defineConfig({
  // 开启 Clean URLs，去掉 .html 后缀
  title: 'iPXE-All-Ready',
  description: 'All is truly All. Ready is truly Ready.',
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
              { text: 'Ch1: Architecture & Core Link', link: '/guide/architecture' }
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
              { text: '前言', link: '/zh/guide/preface' }, // 新增前言链接
              { text: '第一章：架构设计与核心链路', link: '/zh/guide/architecture' }
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