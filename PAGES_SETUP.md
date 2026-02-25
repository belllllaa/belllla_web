# GitLab Pages 部署说明

## 一、确认项目可见性为 Public

1. 打开 https://gitlab.com/bellllla/belllla_web
2. 左侧菜单 **Settings** → **General**
3. 找到 **Visibility, project features, permissions**
4. 确认 **Project visibility** 为 **Public**（Private 项目默认禁用 Pages）

## 二、检查 CI/CD 流水线

1. 左侧菜单 **Build** → **Pipelines**
2. 查看最新流水线状态，应为 **passed**（绿色）
3. 若失败，点击进入查看具体错误

## 三、查看 Pages 部署状态

1. 左侧菜单 **Deploy** → **Pages**
2. 部署成功后会出现访问地址：**https://bellllla.gitlab.io/belllla_web/**

## 四、若仍无法访问

- 确保已推送最新代码（含 .gitlab-ci.yml）
- 等待 2–5 分钟让部署完成
- 在中国大陆需使用 VPN 才能访问 gitlab.io
