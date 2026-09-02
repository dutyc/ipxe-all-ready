// Kurrent 官网兼文档站（VitePress）：zh-CN 默认（root 路径），en 英文子路径。
// 品牌：Kurrent（周流）· Make bare metal flow · logo = 六虚（docs/public/logo.svg）
import { defineConfig } from 'vitepress'

export default defineConfig({
  lang: 'zh-CN',
  title: 'Kurrent（周流）',
  description: 'Make bare metal flow — 云原生无状态裸金属交付',
  head: [['link', { rel: 'icon', href: '/logo.svg' }]],
  cleanUrls: true,
  lastUpdated: true,
  locales: {
    root: {
      label: '简体中文',
      lang: 'zh-CN',
      themeConfig: {
        logo: '/logo.svg',
        nav: [
          { text: '首页', link: '/' },
          { text: '指南', link: '/guide/deployment' },
          { text: 'English', link: '/en/' },
        ],
        sidebar: {
          '/guide/': [
            {
              text: '部署与使用',
              items: [
                { text: '多机部署指南', link: '/guide/deployment' },
              ],
            },
          ],
        },
        outline: { label: '本页目录' },
        docFooter: { prev: '上一篇', next: '下一篇' },
        darkModeSwitchLabel: '主题',
        lightModeSwitchTitle: '切换到浅色模式',
        darkModeSwitchTitle: '切换到深色模式',
        sidebarMenuLabel: '目录',
        returnToTopLabel: '回到顶部',
        lastUpdated: { text: '最后更新于', formatOptions: { dateStyle: 'short', timeStyle: 'medium' } },
        socialLinks: [{ icon: 'github', link: 'https://github.com/dutyc/kurrent' }],
        footer: {
          message: 'Kurrent（周流）· Make bare metal flow',
          copyright: 'Apache-2.0 License · <a href="https://github.com/dutyc/kurrent">github.com/dutyc/kurrent</a>',
        },
      },
    },
    en: {
      label: 'English',
      lang: 'en',
      themeConfig: {
        logo: '/logo.svg',
        nav: [
          { text: 'Home', link: '/en/' },
          { text: 'Guide', link: '/en/guide/deployment' },
          { text: '简体中文', link: '/' },
        ],
        sidebar: {
          '/en/guide/': [
            {
              text: 'Deployment & Usage',
              items: [
                { text: 'Multi-Node Deployment Guide', link: '/en/guide/deployment' },
              ],
            },
          ],
        },
        outline: { label: 'On this page' },
        docFooter: { prev: 'Previous', next: 'Next' },
        darkModeSwitchLabel: 'Theme',
        lightModeSwitchTitle: 'Switch to light mode',
        darkModeSwitchTitle: 'Switch to dark mode',
        sidebarMenuLabel: 'Menu',
        returnToTopLabel: 'Back to top',
        lastUpdated: { text: 'Last updated', formatOptions: { dateStyle: 'short', timeStyle: 'medium' } },
        socialLinks: [{ icon: 'github', link: 'https://github.com/dutyc/kurrent' }],
        footer: {
          message: 'Kurrent · Make bare metal flow',
          copyright: 'Apache-2.0 License · <a href="https://github.com/dutyc/kurrent">github.com/dutyc/kurrent</a>',
        },
      },
    },
  },
})
