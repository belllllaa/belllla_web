# 推送到 GitLab（换电脑前必做）

## 1. 在 GitLab 上新建空项目

1. 登录你的 GitLab（如 https://gitlab.com 或公司自建地址）
2. 点击 **New project** → **Create blank project**
3. 填写 **Project name**（例如 `qmt001bb`）
4. **不要**勾选 "Initialize repository with a README"
5. 创建后记下仓库地址，例如：
   - HTTPS: `https://gitlab.com/你的用户名/qmt001bb.git`
   - SSH: `git@gitlab.com:你的用户名/qmt001bb.git`

## 2. 在本机添加远程并推送

在项目目录 `qmt001bb` 下打开终端，执行（把下面的地址换成你的 GitLab 仓库地址）：

```powershell
cd "c:\Users\bellaBB\Desktop\qmt001bb"

# 添加 GitLab 远程（二选一）
git remote add origin https://gitlab.com/你的用户名/qmt001bb.git
# 或 SSH：
# git remote add origin git@gitlab.com:你的用户名/qmt001bb.git

# 推送到 GitLab（主分支可能是 master 或 main，按 GitLab 提示来）
git push -u origin master
```

若 GitLab 新建项目默认分支是 `main`，而本地是 `master`，可以：

```powershell
git push -u origin master:main
```

之后在 GitLab 上把默认分支改为 `main` 即可。

## 3. 换电脑后拉取项目

在新电脑上：

```powershell
git clone https://gitlab.com/你的用户名/qmt001bb.git
cd qmt001bb
```

即可得到完整项目（不含原 `references/Sequoia`、`references/strategy-vnpy`、`belllla_web` 的 git 历史，仅当前文件快照）。

---

**说明**：子目录 `references/Sequoia`、`references/strategy-vnpy`、`belllla_web` 里原来的 `.git` 已备份为 `git_bak`（未提交），以便整仓作为单仓库推送。若需要这些子项目的独立历史，可在换电脑后从原始来源重新 clone 对应仓库。
