# SportsMed-CDM 线上部署指南（Render 免费版）

本指南把系统部署到 [Render](https://render.com) 的免费 Web Service 上，
得到一个 `https://xxx.onrender.com` 的公网地址。访问需要输入口令
（当前为 `SportsMedCDM2026`），API 密钥通过环境变量注入，**不进代码库**。

---

## 一、准备工作（一次性）

1. 一个 **GitHub 账号**（github.com）。
2. 一个 **Render 账号**（render.com，可直接用 GitHub 账号登录）。免费版无需绑卡。

## 二、把代码推到 GitHub

在本文件夹打开终端（PowerShell），执行：

```powershell
git init
git add .
git commit -m "SportsMed-CDM 线上部署版"
```

然后去 GitHub 新建一个仓库（建议选 **Private 私有**），按页面提示推送：

```powershell
git remote add origin https://github.com/<你的用户名>/sportsmed-cdm.git
git branch -M main
git push -u origin main
```

> `.gitignore` 已配置好：`config.json`（含密钥）、`output/`（学生轨迹）不会被推上去。

## 三、在 Render 上创建服务

1. 登录 Render → 点 **New → Blueprint**。
2. 选择刚才的 GitHub 仓库（首次需要授权 Render 访问）。
3. Render 会自动读取仓库里的 `render.yaml`，识别出服务 `sportsmed-cdm`。
4. 部署前它会要求填写环境变量 **`LLM_API_KEY`**：
   把阿里云百炼的 API Key（`sk-` 开头那串，在本地 `config.json` 里）粘贴进去。
5. 点 **Apply / Deploy**，等 2–5 分钟构建完成。

完成后你会得到形如 `https://sportsmed-cdm.onrender.com` 的地址，
打开会先看到口令页，输入 `SportsMedCDM2026` 即可进入系统。

> 也可以不用 Blueprint，手动 New → Web Service，此时需要自己填：
> Build Command = `pip install -r requirements.txt`，
> Start Command = `gunicorn -w 1 --threads 8 --timeout 180 -b 0.0.0.0:$PORT app:app`，
> 并手动添加环境变量 `ACCESS_CODE` 和 `LLM_API_KEY`。

## 四、可配置的环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `ACCESS_CODE` | 访问口令；设为空字符串则关闭门禁 | `SportsMedCDM2026` |
| `LLM_API_KEY` | 百炼 API Key（必填，线上没有 config.json） | 无 |
| `LLM_BASE_URL` | LLM 兼容端点 | 百炼 compatible-mode |
| `LLM_MODEL` | 模型名 | `qwen3.6-27b` |
| `SECRET_KEY` | 登录 Cookie 签名密钥；不设则每次重启随机（重启后学生需重新输口令） | 随机 |

在 Render 控制台 → 该服务 → Environment 里改，保存后自动重新部署。

## 五、免费版的已知限制（务必了解）

1. **闲置休眠**：15 分钟无人访问后实例休眠，下一个访问者要等约 30–60 秒冷启动。
   教学前可提前打开一次网址"预热"。
2. **轨迹不持久**：`output/` 里的接诊轨迹存在容器磁盘上，**每次重启/重新部署都会清空**。
   需要留存测评数据时，请在课后及时通过 Render 控制台 Shell 下载，
   或以后升级为持久盘/对象存储方案。
3. **服务器在国外**：国内访问 onrender.com 一般可达但速度一般；如果学生普遍打不开，
   建议换"方案二：国内云服务器"。
4. **单实例单进程**：会话存内存，`render.yaml` 已固定 `-w 1` 单 worker，请勿改成多 worker。
5. **代码更新**：本地改完代码后 `git add . && git commit -m "..." && git push`，
   Render 会自动重新部署。

## 六、本地运行不受影响

本地仍然双击 `启动.bat` 即可，`config.json` 继续生效。
唯一变化：本地打开也会先要求输入口令 `SportsMedCDM2026`。
如果本地不想要口令，启动前设 `set ACCESS_CODE=` 即可。
